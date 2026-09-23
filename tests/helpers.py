"""Shared helpers for the tests. No test here calls a paid provider."""

from __future__ import annotations

from typing import Any

from sanchopanza import Answer, Decision, Thresholds, truth
from sanchopanza.journal import MemoryJournal
from sanchopanza.squire import Squire


def decision(point: str, **answers: Answer) -> Decision:
    return Decision(point=point, answers=answers, provider="test", model="t")


def score(value: float, confidence: float) -> Answer:
    return Answer(kind="score", score=value, confidence=confidence)


def choice(value: str, confidence: float, **probabilities: float) -> Answer:
    return Answer(kind="choice", choice=value, confidence=confidence, probabilities=probabilities)


def yes(p: float) -> Answer:
    return truth(p)


def thresholds(**changes: Any) -> Thresholds:
    return Thresholds().with_(**changes)


def squire(decider: Any, **changes: Any) -> tuple[Squire, MemoryJournal]:
    journal = MemoryJournal()
    return Squire(
        decider, thresholds=thresholds(**changes), journal=journal, brief="brief"
    ), journal
