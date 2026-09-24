"""The loop guard: has this already been established, and is this check a repeat?

This is the point with the largest *measured* waste behind it. A preregistered study of
4,644 coding-agent runs over 24 deterministic tasks and seven models found that runs which
fell into redundant verification at its extreme level cost **18x the clean-run median**,
made 2.5x the tool calls and took 3x the wall time, **with no improvement in success**
[Weinberger and Hozez, 2026]. The waste is tool-borne and it escalates: the agent finishes,
then checks, then checks the check. The same paper measures the cheaper cousin, a discarded
solution branch, at 1.9x the median, token-borne rather than tool-borne.

Neither of those is a hard problem of judgment. "Is the thing you were asked for already
established by what you have?" is a reading of the goal against the evidence, which is what
this model class does. The saving is not a few tokens of context: it is the whole tail of a
run that should have stopped.

**It advises; it never denies.** Stopping too early is the expensive error and the operator
sees it, so the policy speaks only above `saturated`, and what it produces is a note for the
orchestrator (`additionalContext` in a PostToolUse hook), never a refusal. An agent that is
told "you already have this" and disagrees carries on, and that is the correct behaviour.

Not yet measured against an independent annotator: `benches/loop.jsonl` is single-author,
and this point is newer than the ones in the paper's Section 5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..contract import Decision, Question, Truth
from ..policy import Thresholds, probability
from ..text import truncate

GOAL_LIMIT = 500
DONE_LIMIT = 1600
ACTION_LIMIT = 300


def questions(
    *, goal: str, done: str, pending: str = "", checks: Sequence[str] = ()
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """`done` is what the agent has established; `pending` the action it is about to take."""
    state: dict[str, Any] = {
        "goal": truncate(goal, GOAL_LIMIT),
        "done": truncate(done, DONE_LIMIT),
    }
    if pending:
        state["pending"] = truncate(pending, ACTION_LIMIT)
    if checks:
        state["checks_already_run"] = [truncate(c, ACTION_LIMIT) for c in checks]
    qs: dict[str, Question] = {
        "goal_met": Truth(
            "Does `done` already establish everything `goal` asks for, so that an answer "
            "could be written now without anything further?",
            criteria={
                "true": {
                    "what": "Every part of the goal has a concrete result in `done`: the "
                    "figures asked for are there, the change asked for is made and its check "
                    "passed, the question asked has an answer with its source",
                    "examples": [
                        "goal: 'find the fine and the date'; done: both, from the ruling",
                        "goal: 'fix the failing test'; done: the edit, and the suite passing",
                    ],
                },
                "false": {
                    "what": "Some part is missing, unverified, or only partially covered; or "
                    "`done` records attempts rather than results",
                    "examples": [
                        "goal asks for two figures and `done` has one",
                        "done: 'searched three times, nothing conclusive yet'",
                    ],
                },
            },
        ),
        "repeats_check": Truth(
            "Is `pending` a check of something `done` (or `checks_already_run`) has already "
            "checked, with the same subject and the same expected outcome?",
            criteria={
                "true": {
                    "what": "Re-running a verification that already passed, re-reading a "
                    "document already read for the same purpose, re-confirming a figure "
                    "already confirmed against the same source",
                    "examples": [
                        "pending: 'run the test suite again'; done: the suite already passed "
                        "after the last edit, and nothing changed since",
                    ],
                },
                "false": {
                    "what": "It checks something new, checks the same thing against a "
                    "different source, or re-checks after a change that could have broken it",
                    "examples": [
                        "pending: 'run the suite'; done: the suite passed, then the code was "
                        "edited again",
                        "pending: 'confirm the figure in the official bulletin'; done: the "
                        "figure came from a newspaper",
                    ],
                },
            },
        ),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class LoopAdvice:
    """What to tell the orchestrator, if anything. `message` is empty when it stays quiet."""

    message: str
    goal_met: float
    repeats_check: float

    @property
    def speaks(self) -> bool:
        return bool(self.message)


def decide(decision: Decision, t: Thresholds) -> LoopAdvice:
    """Speak only above `saturated`, and only to advise. Silence is the default."""
    if decision.failed:
        return LoopAdvice("", 0.0, 0.0)
    met, repeat = decision.answer("goal_met"), decision.answer("repeats_check")
    pm, pr = probability(met), probability(repeat)
    notes: list[str] = []
    if not met.empty and pm >= t.saturated:
        notes.append(
            f"what you were asked for appears to be established already ({pm:.2f}): "
            "consider writing the answer instead of gathering more"
        )
    if not repeat.empty and pr >= t.saturated:
        notes.append(
            f"this check looks like one already run with the same outcome ({pr:.2f}): "
            "re-running it is unlikely to change anything"
        )
    return LoopAdvice("; ".join(notes), pm, pr)
