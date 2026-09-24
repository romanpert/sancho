"""Page triage: does a fetched page deserve a place in the large model's context?

Measured (paper, D3): 14/16; both misses at low confidence, one kept on purpose. This is the
largest saving lever the evidence points to (tokens explain 80 % of performance variance in
multi-agent research systems), and the one with the cheapest error: a dropped page costs
coverage, a kept one costs tokens. Hence the asymmetry: in doubt, the page enters.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..contract import Choice, Decision, Question, Truth
from ..policy import Thresholds, confident, probability
from ..text import excerpt, truncate
from . import injection

TEXT_LIMIT = 1500

SOURCE_KINDS: dict[str, dict[str, Any]] = {
    "official_records": {
        "what": "Government, court, registry, regulator or official statistics portals",
        "examples": ["court rulings", "official gazette", "company registry", "decrees"],
    },
    "news": {
        "what": "Newspapers, wire services, broadcast and digital news outlets",
        "not_for": "press releases hosted by the organization itself",
    },
    "academic": {"what": "Peer-reviewed papers, theses, working papers, scientific databases"},
    "corporate": {"what": "The organization's own site, filings, press releases, product pages"},
    "social": {"what": "Social networks, forums, blogs, video platforms, personal posts"},
    "data_api": {
        "what": "Structured datasets, catalogs and APIs meant to be queried programmatically",
        "examples": ["seismic catalogs", "open data portals", "statistical APIs"],
    },
    "other": {"what": "None of the above, or impossible to tell"},
}


def questions(
    *, purpose: str, title: str = "", url: str = "", text: str
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {
        "purpose": truncate(purpose, 400),
        "title": truncate(title, 200),
        "url": truncate(url, 300),
        # Head plus the window that matches the purpose, not just the head: see `text.excerpt`.
        # For anything at or under the limit this is the text unchanged.
        "text": excerpt(text, purpose, TEXT_LIMIT),
    }
    qs: dict[str, Question] = {
        "relevant": Truth("Does `text` address what `purpose` is looking for?"),
        "evidence": Truth(
            "Does `text` contain concrete, citable facts about `purpose` (dates, names, "
            "figures, document references), not just passing mentions?"
        ),
        "injection": injection.question(),
        "source_kind": Choice("Which kind of source is this page?", SOURCE_KINDS),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Triage:
    keep: bool
    reason: str
    relevance: float
    evidence: float
    injection: float
    source_kind: str


def decide(
    decision: Decision,
    t: Thresholds,
    *,
    allowed_kinds: Iterable[str] | None = None,
    denied_kinds: Iterable[str] | None = None,
) -> Triage:
    """Whether a page enters the context. In doubt it enters: cutting costs coverage.

    `allowed_kinds` / `denied_kinds` filter on the source kind the decider already returned,
    in code and at no extra cost. They exist because of a measured failure: on the
    steerability bench the criterion "official primary sources, not press citing them" was
    expressed only in the purpose, the relevance question answered 0.98 (the article *is*
    about the topic), and the page was kept. The answer was in the same decision all along:
    `source_kind` came back `news` at confidence 1.00, and the policy threw it away.

    So a provenance requirement belongs here rather than in the purpose text. It is also the
    better-calibrated route: Choice is the best-calibrated primitive in this model class
    (ECE 0.035 against 0.14 for Truth, paper 5.8), and a set membership test in code cannot
    drift. Unknown or low-confidence kinds keep the page, like every other doubt.
    """
    if decision.failed:
        return Triage(True, "decider unavailable", 0.0, 0.0, 0.0, "other")
    inj = probability(decision.answer("injection"))
    relevance = decision.answer("relevant").truth
    evidence = probability(decision.answer("evidence"))
    answer_kind = decision.answer("source_kind")
    kind = answer_kind.choice or "other"
    if inj > t.injection:
        return Triage(False, f"instruction injection ({inj:.2f})", 0.0, 0.0, inj, kind)
    if (allowed_kinds or denied_kinds) and confident(answer_kind, t.act):
        unwanted = (allowed_kinds is not None and kind not in set(allowed_kinds)) or (
            denied_kinds is not None and kind in set(denied_kinds)
        )
        if unwanted:
            reason = f"source kind {kind} ({answer_kind.confidence:.2f}) is not wanted here"
            return Triage(
                False, reason, probability(decision.answer("relevant")), evidence, inj, kind
            )
    if relevance is None:
        return Triage(True, "no relevance data", 0.0, evidence, inj, kind)
    if relevance < t.relevance:
        return Triage(False, f"not relevant ({relevance:.2f})", relevance, evidence, inj, kind)
    return Triage(True, f"relevant ({relevance:.2f})", relevance, evidence, inj, kind)


# --- D3b: does this page repeat what the agent already has? -----------------------------
#
# Triage asks whether a page is about the purpose. It does not ask whether the agent has
# already read the same thing somewhere else, and in a fetch-heavy job that is where the
# tokens are: twenty sources covering one event carry the same five facts and one of them
# is the original. Redundancy is the lever the end-to-end A/B could not exercise, because
# its agent fetched one or two documents per task (benchmarks/ab, docs/savings.md).
#
# The asymmetry is the same as triage's and for the same reason: dropping a page that did
# carry something new costs coverage, keeping one costs tokens. `t.redundant` is the same
# knob the search point uses for a repeated query, because it is the same reading.

DIGEST_LIMIT = 1200


def redundancy_questions(
    *, purpose: str, text: str, known: str
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """`known` is a digest of what the agent already holds: titles, facts, or both."""
    state = {
        "purpose": truncate(purpose, 400),
        "known": truncate(known, DIGEST_LIMIT),
        "text": excerpt(text, purpose, TEXT_LIMIT),
    }
    qs: dict[str, Question] = {
        "adds_nothing": Truth(
            "For the work described in `purpose`, does `text` add nothing that `known` does "
            "not already carry: no new figure, date, name, outcome, qualification or source?",
            criteria={
                "true": {
                    "what": "The same facts in different words, a shorter version, a wire "
                    "story reprinted, or a page that only cites what `known` already states",
                    "examples": [
                        "known: '1,240 homes damaged, 312 severe'; text: an article giving "
                        "the same two figures and nothing else"
                    ],
                },
                "false": {
                    "what": "Any new value, any correction, any date or source that `known` "
                    "lacks, or the same facts attributed to a different source when the work "
                    "is about corroboration",
                    "examples": [
                        "known: '1,240 homes damaged'; text: the same, plus the municipality "
                        "breakdown",
                        "known: a newspaper's figure; text: the official bulletin's figure, "
                        "when `purpose` is to corroborate it",
                    ],
                },
            },
        )
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Redundancy:
    drop: bool
    reason: str
    probability: float


def decide_redundancy(decision: Decision, t: Thresholds) -> Redundancy:
    """Drop only on a confident yes. No data, a failure or doubt all keep the page."""
    if decision.failed:
        return Redundancy(False, "decider unavailable: keep", 0.0)
    answer = decision.answer("adds_nothing")
    p = probability(answer)
    if answer.empty:
        return Redundancy(False, "no data: keep", p)
    if p >= t.redundant and confident(answer, t.act):
        return Redundancy(True, f"adds nothing new ({p:.2f})", p)
    return Redundancy(False, f"may add something ({p:.2f})", p)
