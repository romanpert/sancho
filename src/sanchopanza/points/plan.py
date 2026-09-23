"""A plan as a scored DAG: value, saturation and model per line; dependencies per pair.

Measured (paper, D5 and G3): pairwise dependency 20/20; on a full 8-line plan the raw pairs
give 40 % precision (transitive edges, two ties reversed) and, after `dag.build_dag`, 100 %
precision, 88 % recall and the exact parallel waves. The decider reads pairs; the graph is
built by code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..contract import Choice, Decision, Question, Score, Truth
from ..policy import Thresholds, probability
from ..text import truncate
from . import routing
from .triage import SOURCE_KINDS

MAX_LINES_FOR_DAG = 8  # n(n-1) pairs: 56 decisions for 8 lines, half a cent. Beyond that, no.


def line_questions(
    line: Mapping[str, Any], *, brief: str = "", others: Sequence[str] = (), findings: str = ""
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """Before a round: what each line is worth, whether it depends on another, whether it is
    already exhausted, and how much model it needs."""
    state = {
        "brief": truncate(brief, 400),
        "line": {
            "title": truncate(str(line.get("title", "")), 200),
            "goal": truncate(str(line.get("goal", "")), 600),
        },
        "other_lines": [truncate(o, 120) for o in list(others)[:15]],
        "findings_so_far": truncate(findings, 1200),
    }
    qs: dict[str, Question] = {
        "value": Score(
            "How much would completing `line` contribute to the deliverable described in `brief`?",
            (
                {"summary": "Marginal: nice to have, the deliverable stands without it"},
                {"summary": "Useful: fills a gap a reader would notice"},
                {"summary": "Essential: the deliverable is wrong or empty without it"},
            ),
        ),
        "depends_on_others": Truth(
            "Does `line` need the results of one of `other_lines` before it can start?"
        ),
        "saturated": Truth(
            "Given `findings_so_far`, is `line` already answered well enough that more "
            "searching would add little?"
        ),
        "complexity": Score(
            "How demanding is `line` for a research assistant with web search?",
            routing.COMPLEXITY_LEVELS,
        ),
        "source_kind": Choice("Which kind of source will answer `line` best?", SOURCE_KINDS),
    }
    return state, qs


def dependency_questions(
    *, a_title: str, a_goal: str, b_title: str, b_goal: str
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {
        "line_a": {"title": truncate(a_title, 200), "goal": truncate(a_goal, 500)},
        "line_b": {"title": truncate(b_title, 200), "goal": truncate(b_goal, 500)},
    }
    qs: dict[str, Question] = {
        "b_needs_a": Truth(
            "Does `line_b` need the output of `line_a` before it can start, so that "
            "running them in parallel would make `line_b` wait or repeat work?",
            {
                "true": {
                    "what": "line_b consumes a list, dataset, selection or verdict that line_a "
                    "produces",
                    "examples": [
                        "a lists the rulings; b writes a profile of the ten most important",
                        "a consolidates the register; b draws charts from the register",
                    ],
                },
                "false": {
                    "what": "line_b can start from the brief alone, even if the two lines "
                    "share a topic or will be merged later",
                    "examples": [
                        "a describes the legal framework; b lists the rulings",
                        "a profiles the plaintiffs; b profiles the defendants",
                    ],
                },
            },
        )
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class LineEvaluation:
    priority: float
    parallel: bool
    saturated: bool
    tier: routing.Tier
    source_kind: str
    reason: str


def decide_line(decision: Decision, t: Thresholds) -> LineEvaluation:
    """Priority = expected value discounted by saturation."""
    if decision.failed:
        return LineEvaluation(0.5, True, False, "default", "other", "decider unavailable")
    value = decision.answer("value").score
    saturated = probability(decision.answer("saturated")) >= t.saturated
    depends = probability(decision.answer("depends_on_others")) >= 0.7
    route = routing.decide(decision, t)
    kind = decision.answer("source_kind").choice or "other"
    if value is None:
        return LineEvaluation(0.5, not depends, saturated, route.tier, kind, "no value estimate")
    priority = round((value / 2.0) * (0.2 if saturated else 1.0), 3)
    return LineEvaluation(priority, not depends, saturated, route.tier, kind, route.reason)
