"""The contract between an agent harness and a decision model.

A *decider* answers closed questions about a piece of text state: pick one option,
place on a scale, or say how likely a proposition is. It never generates text. It
returns probabilities and a confidence; code turns those into actions with thresholds.

Nothing in this module knows which model is behind the contract. TypeSafe's Jev, a local
classifier, a vision model, or an LLM forced into a schema all fit behind `Decider`. That
is what makes the squire swappable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

QuestionKind = Literal["choice", "score", "truth"]
State = str | Mapping[str, Any] | Sequence[Any]


@dataclass(frozen=True, slots=True)
class Choice:
    """One option among several, mutually exclusive. `options` maps name to criteria."""

    instructions: str | Mapping[str, Any]
    options: Mapping[str, Any]
    kind: QuestionKind = field(default="choice", init=False)

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError("a choice needs at least two options")


@dataclass(frozen=True, slots=True)
class Score:
    """A position on a scale of 2 to 10 levels, each described as a situation."""

    instructions: str | Mapping[str, Any]
    levels: Sequence[str | Mapping[str, Any]]
    kind: QuestionKind = field(default="score", init=False)

    def __post_init__(self) -> None:
        if not 2 <= len(self.levels) <= 10:
            raise ValueError("a score has between 2 and 10 levels")


@dataclass(frozen=True, slots=True)
class Truth:
    """A yes or no. Optional `criteria` describe the boundary of `true` and `false`."""

    instructions: str | Mapping[str, Any]
    criteria: Mapping[str, Any] | None = None
    kind: QuestionKind = field(default="truth", init=False)


Question = Choice | Score | Truth


@dataclass(frozen=True, slots=True)
class Answer:
    """The calibrated answer to one question. Immutable: it is evidence of why code acted."""

    kind: QuestionKind
    confidence: float
    choice: str | None = None
    score: float | None = None
    truth: float | None = None
    probabilities: Mapping[str, float] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        """True when the decider did not answer: code must use its default."""
        return self.choice is None and self.score is None and self.truth is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "confidence": self.confidence,
            "choice": self.choice,
            "score": self.score,
            "truth": self.truth,
            "probabilities": dict(self.probabilities),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Answer:
        return cls(
            kind=raw.get("kind", "truth"),
            confidence=float(raw.get("confidence", 0.0)),
            choice=raw.get("choice"),
            score=raw.get("score"),
            truth=raw.get("truth"),
            probabilities=dict(raw.get("probabilities") or {}),
        )


@dataclass(frozen=True, slots=True)
class Decision:
    """A batch of answers to one state, with what it cost to obtain them."""

    point: str
    answers: Mapping[str, Answer]
    provider: str
    model: str
    input_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None

    def answer(self, key: str) -> Answer:
        """The answer to one question, or an empty one if the provider did not return it."""
        return self.answers.get(key) or Answer(kind="truth", confidence=0.0)

    @property
    def failed(self) -> bool:
        return self.error is not None


class DeciderUnavailable(RuntimeError):
    """The provider cannot answer. Callers continue with their default; they never stop."""


@runtime_checkable
class Decider(Protocol):
    """The only thing a harness knows about a decision provider."""

    name: str

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        """Answer every question about the state in one call.

        Raises `DeciderUnavailable` when it cannot. Never returns made-up answers.
        """
        ...


def truth_confidence(value: float) -> float:
    """Confidence of a yes/no: 1 at the extremes, 0 at 0.5."""
    return abs(2.0 * value - 1.0)


def empty_answer(kind: QuestionKind) -> Answer:
    return Answer(kind=kind, confidence=0.0)


def empty_decision(point: str, provider: str = "none", error: str | None = None) -> Decision:
    return Decision(point=point, answers={}, provider=provider, model="-", error=error)
