"""Model per subtask: how much model does this piece of work deserve?

Measured (paper, D1): 17/20 raw agreement on a 3-level complexity scale; 100 % when acting
at confidence >= 0.75; a small LLM scored 8/20 on the same cases. The complexity question is
a Score, the least reliable primitive in our calibration data, which is why `act` (0.75)
gates the downgrade and why tasks about identifiable people never go to the light tier.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..contract import Decision, Question, Score, Truth
from ..policy import Thresholds, probability
from ..text import truncate

Tier = Literal["light", "default", "deep"]
TIERS: tuple[Tier, ...] = ("light", "default", "deep")

COMPLEXITY_LEVELS: tuple[dict[str, Any], ...] = (
    {
        "summary": "Lookup or extraction: find a specific fact, list, figure or document in "
        "sources that are named or obvious, and copy it out faithfully",
        "signals": ["one entity", "one source type", "no judgment needed", "answer is a value"],
    },
    {
        "summary": "Bounded investigation: consult several sources, cross-check them and "
        "summarize; a careful generalist can do it with ordinary care",
        "signals": ["a few entities", "some cross-checking", "moderate ambiguity"],
    },
    {
        "summary": "Open-ended or high-stakes analysis: ambiguous scope, conflicting sources, "
        "legal, financial or reputational judgment, or synthesis across many lines",
        "signals": ["conflicting evidence", "legal exposure", "many entities", "novel synthesis"],
    },
)

TASK_LIMIT = 1200


def questions(
    task: str, *, brief: str = "", profile: str = ""
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """Before delegating: how demanding is it, does it need a browser, does it touch a person."""
    state: dict[str, Any] = {"task": truncate(task, TASK_LIMIT), "brief": truncate(brief, 400)}
    if profile:
        state["profile"] = profile
    qs: dict[str, Question] = {
        "complexity": Score(
            "How demanding is `task` for a research assistant with web search?",
            COMPLEXITY_LEVELS,
        ),
        "needs_browser": Truth(
            "Does completing `task` require operating an interactive website (login, search "
            "forms, pagination by clicks, dropdown filters) rather than fetching pages by URL?"
        ),
        "person_risk": Truth(
            "Does `task` involve statements about an identifiable natural person that could "
            "harm their reputation if they were wrong?"
        ),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Routing:
    tier: Tier
    reason: str
    complexity: float | None
    confidence: float
    person_risk: bool
    needs_browser: bool


def decide(decision: Decision, t: Thresholds, *, default: Tier = "default") -> Routing:
    """Which tier a task deserves. Downgrading needs `act`; upgrading needs `relax` and leave."""
    complexity = decision.answer("complexity")
    risk = probability(decision.answer("person_risk")) >= 0.7
    browser = probability(decision.answer("needs_browser")) >= 0.7
    if decision.failed:
        return Routing(default, "decider unavailable", None, 0.0, risk, browser)
    if complexity.empty or complexity.score is None:
        return Routing(default, "no complexity score", None, 0.0, risk, browser)
    value, confidence = complexity.score, complexity.confidence
    if value >= 1.5 and confidence >= t.relax and t.allow_upgrade:
        return Routing(
            "deep",
            f"complexity {value:.2f} at confidence {confidence:.2f}",
            value,
            confidence,
            risk,
            browser,
        )
    if value >= 1.5:
        return Routing(
            default,
            "high complexity but upgrades are not allowed",
            value,
            confidence,
            risk,
            browser,
        )
    if value <= 0.5 and confidence >= t.act and not risk:
        return Routing(
            "light",
            f"complexity {value:.2f} at confidence {confidence:.2f}",
            value,
            confidence,
            risk,
            browser,
        )
    if value <= 0.5 and risk:
        return Routing(
            default,
            "simple task but about an identifiable person",
            value,
            confidence,
            risk,
            browser,
        )
    return Routing(
        default,
        f"complexity {value:.2f}, confidence {confidence:.2f}: default",
        value,
        confidence,
        risk,
        browser,
    )
