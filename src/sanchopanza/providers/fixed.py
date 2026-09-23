"""Deciders for tests and demos: always the same answers, or always broken."""

from __future__ import annotations

from collections.abc import Mapping

from ..contract import Answer, DeciderUnavailable, Decision, Question, State


class FixedDecider:
    """Returns the same answers for every call and counts the calls."""

    name = "fixed"

    def __init__(self, answers: Mapping[str, Answer], *, cost_usd: float = 0.0001) -> None:
        self._answers = dict(answers)
        self._cost = cost_usd
        self.calls = 0

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        self.calls += 1
        return Decision(
            point=point,
            answers={k: v for k, v in self._answers.items() if k in questions},
            provider=self.name,
            model="fixed",
            input_tokens=1000,
            cost_usd=self._cost,
        )


class BrokenDecider:
    """Always raises `DeciderUnavailable`. For testing fail-open paths."""

    name = "broken"

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        raise DeciderUnavailable("provider down")
