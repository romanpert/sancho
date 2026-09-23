"""Tool selection: which groups of a tool catalog does this request need?

Not yet measured on a public bench (paper, pending item 7). The evidence that motivates it
is the cost side: a harness that binds every schema on every step pays for the whole catalog
each turn (250 schemas is 25-38k tokens per step in one production agent), and a client-side
catalog middleware in another measured 51-60 % fewer tokens per call before being switched
off for lack of a reliable selector. Generic retrievers do badly on tool corpora (ToolRet,
arXiv 2503.01763); a two-stage selection with a decision model cut wrong skill loads from
16.8 % to 7.3 % over 182 skills (TypeSafe, skill suggestion cookbook).

The asymmetry is the opposite of page triage: leaving a needed group out costs capability
(the agent cannot call what it cannot see), keeping an extra one costs tokens. So a group
is dropped only when the probability that it is needed is low, `always` groups never leave,
and the selection is never empty. One Truth per group, all in one call: several may apply.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..contract import Decision, Question, Truth
from ..policy import Thresholds, probability
from ..text import truncate

GROUPS_PER_CALL = 48  # keeps the state well under the request budget; larger catalogs chunk
PURPOSE_LIMIT = 400
CLUES_LIMIT = 300
ABOUT_LIMIT = 160


def _group(raw: Mapping[str, Any]) -> dict[str, Any]:
    name = str(raw.get("name", "")).strip()
    about = truncate(raw.get("about", "") or raw.get("description", ""), ABOUT_LIMIT)
    tags = raw.get("tags") or ()
    out: dict[str, Any] = {"name": name, "about": about}
    if tags:
        out["tags"] = [str(t) for t in tags]
    return out


def questions(
    *, purpose: str, catalog: Sequence[Mapping[str, Any]], clues: str = ""
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """One Truth per catalog group: would the work on `purpose` need tools from it?

    Question ids are positional (`needed_0`, ...) so that any group name is safe; the group
    is referenced by path in the instructions, which is what the model reads.
    """
    groups = [_group(g) for g in catalog]
    state: dict[str, Any] = {"purpose": truncate(purpose, PURPOSE_LIMIT), "catalog": groups}
    if clues:
        state["clues"] = truncate(clues, CLUES_LIMIT)
    qs: dict[str, Question] = {}
    for i, group in enumerate(groups):
        qs[f"needed_{i}"] = Truth(
            f"Would an agent working on `purpose` (with `clues`, if present) need to call "
            f"any tool from the group `catalog[{i}]` (`{group['name']}`: {group['about']})?",
            criteria={
                "true": {
                    "what": "The group's tools would plausibly be called to answer or act on "
                    "`purpose`: same domain, jurisdiction, entity type or data the request "
                    "is about",
                },
                "false": {
                    "what": "The group covers a different domain, jurisdiction or data type "
                    "than `purpose` needs, or `purpose` can be handled without it",
                },
            },
        )
    return state, qs


@dataclass(frozen=True, slots=True)
class Selection:
    keep: tuple[str, ...]
    dropped: tuple[str, ...]
    reason: str
    probabilities: dict[str, float] = field(default_factory=dict)

    @property
    def narrowed(self) -> bool:
        return bool(self.dropped)


def probabilities_of(
    decision: Decision, catalog: Sequence[Mapping[str, Any]]
) -> dict[str, float | None]:
    """Name to probability that the group is needed; None when the decider said nothing."""
    out: dict[str, float | None] = {}
    for i, raw in enumerate(catalog):
        name = str(raw.get("name", "")).strip()
        answer = decision.answer(f"needed_{i}")
        out[name] = None if decision.failed or answer.empty else probability(answer)
    return out


def select(
    probs: Mapping[str, float | None],
    t: Thresholds,
    *,
    always: Iterable[str] = (),
    failed: bool = False,
) -> Selection:
    """Pure policy over merged probabilities. Never returns an empty selection."""
    names = list(probs)
    pinned = {n for n in always if n in probs}
    known = {n: p for n, p in probs.items() if p is not None}
    if failed or not names:
        return Selection(tuple(names), (), "decider unavailable: full catalog", {})
    if not known:
        return Selection(tuple(names), (), "no data: full catalog", {})

    keep = [n for n in names if n in pinned or probs[n] is None or known.get(n, 0.0) >= t.tools]
    chosen = [n for n in keep if n not in pinned]
    if not chosen:
        best = max(known, key=known.get)
        if best not in keep:
            keep.append(best)
        reason = f"nothing at p >= {t.tools:.2f}: kept best ({best}, {known[best]:.2f})"
    else:
        reason = f"kept {len(keep)}/{len(names)} groups at p >= {t.tools:.2f}"
    order = {n: i for i, n in enumerate(names)}
    keep.sort(key=order.__getitem__)
    dropped = tuple(n for n in names if n not in keep)
    return Selection(tuple(keep), dropped, reason, dict(known))


def decide(
    decision: Decision,
    t: Thresholds,
    *,
    catalog: Sequence[Mapping[str, Any]],
    always: Iterable[str] = (),
) -> Selection:
    """Which groups stay in the model's call. In doubt a group stays: cutting costs capability."""
    return select(probabilities_of(decision, catalog), t, always=always, failed=decision.failed)
