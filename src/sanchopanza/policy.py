"""Thresholds: from calibrated probabilities to actions.

Two principles come from the evidence on routers and from our own measurements:

1. **Asymmetry.** The direction whose error the operator sees (downgrade a model, drop
   a page, deny a command) needs more confidence than the cheap direction (upgrade,
   keep, allow). Badly calibrated routers drift to the majority class; asymmetry stops
   that drift from costing quality.
2. **No data, the default.** Every empty answer, failed call or sub-threshold confidence
   falls back to whatever the harness did before the squire existed. The squire can only
   improve an agent; it can never stop one.

The defaults below are the production thresholds measured in the paper (docs/paper.md).
They were fixed before the runs and never tuned on results. Per-primitive calibration
(Section 5.8 of the paper) says Truth answers are under-confident and Score answers are
the least reliable; `Thresholds.act` applies to Score-driven decisions and is the one to
keep high.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any

from .contract import Answer


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Every knob a policy reads. Flat on purpose: one place, one name per threshold."""

    act: float = 0.75  # confidence needed for the costly direction (downgrade, drop, deny)
    relax: float = 0.60  # confidence needed for the cheap direction (upgrade, keep)
    allow_upgrade: bool = False  # may a task be sent to a deeper model than the default?
    redundant: float = 0.80  # probability that a query repeats an earlier one
    keyword: float = 0.60  # probability that a query is keyword-style (cheap search)
    relevance: float = 0.45  # below this, a page does not enter the context
    injection: float = 0.70  # above this, a page is dropped and logged
    citation: float = 0.80  # confidence needed for an automatic citation verdict
    review: float = 0.70  # signal needed before the squire speaks about a report
    guard: float = 0.70  # probability needed to add a denial on a shell command
    entity_low: float = 0.25  # below: different entity
    entity_high: float = 0.75  # above: same entity; in between: not sure
    classify: float = 0.60  # probability needed to accept a closed-vocabulary label
    tools: float = 0.35  # below this, a tool group leaves the model's call (in doubt, keep)
    saturated: float = 0.70  # probability that a research line is exhausted
    remember: float = 0.70  # probability needed to write a fact to long-term memory
    max_decisions: int = 400  # per job
    max_usd: float = 0.10  # per job

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> Thresholds:
        """Build from a flat mapping (a YAML block, env values). Unknown keys are ignored."""
        raw = raw or {}
        known = {f.name: f.type for f in fields(cls)}
        values: dict[str, Any] = {}
        for key, value in raw.items():
            if key not in known:
                continue
            if key == "allow_upgrade":
                values[key] = _as_bool(value)
            elif key == "max_decisions":
                values[key] = int(value)
            else:
                values[key] = float(value)
        return cls(**values)

    def with_(self, **changes: Any) -> Thresholds:
        return replace(self, **changes)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def confident(answer: Answer, threshold: float) -> bool:
    """True when the answer exists and its confidence reaches the threshold."""
    return not answer.empty and answer.confidence >= threshold


def probability(answer: Answer, default: float = 0.0) -> float:
    """The truth probability of a Truth answer, or `default` when there is none."""
    return answer.truth if answer.truth is not None else default
