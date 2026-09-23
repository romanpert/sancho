"""Citation check as a cascade: literal presence in code, meaning in the decider, doubt to a
human.

Measured (paper, D4 and E3): 19/20 on ordinary claims, 23/24 on claims with numbers; every
miss was an abstention. The one abstention that mattered required counting (seven articles
against "six"), which is exactly where the model card says the model class is weak.

A verifier of a different family, anchored in an external signal (the quote is or is not
in the source), is the recommended correction for the self-preference of LLM judges.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ..contract import Choice, Decision, Question
from ..policy import Thresholds
from ..text import truncate

Verdict = Literal["supported", "contradicted", "unsupported", "fabricated", "review"]
SECTION_LIMIT = 1500

RELATION_TO_VERDICT: dict[str, Verdict] = {
    "supports": "supported",
    "contradicts": "contradicted",
    "says_nothing": "unsupported",
}

ADVICE: dict[Verdict, str] = {
    "supported": "You may cite it.",
    "contradicted": "The source says the opposite: correct the claim or withdraw it.",
    "unsupported": "The quote exists but does not back the claim: find another source.",
    "fabricated": "The quote is not in the source: do not use it.",
    "review": "The decider is not confident enough: mark it as pending human review.",
}


def questions(claim: str, section: str) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {"claim": truncate(claim, 600), "section": truncate(section, SECTION_LIMIT)}
    qs: dict[str, Question] = {
        "relation": Choice(
            "How does `section` relate to `claim`?",
            {
                "supports": "The section states the claim or directly implies that it is true",
                "contradicts": "The section states the opposite of the claim or implies it is "
                "false",
                "says_nothing": "The section does not address what the claim asserts, either way",
            },
        )
    }
    return state, qs


def decide(decision: Decision, t: Thresholds, *, quote_found: bool) -> tuple[Verdict, float]:
    """The verdict and the confidence it is issued with."""
    if not quote_found:
        return "fabricated", 1.0
    if decision.failed:
        return "review", 0.0
    relation = decision.answer("relation")
    if relation.empty or relation.confidence < t.citation:
        return "review", relation.confidence
    return RELATION_TO_VERDICT.get(relation.choice or "", "review"), relation.confidence
