"""Where decisions are written. Every decision leaves a trace or it did not happen.

The event is the audit trail ("why was this model chosen?") and, later, the labelled
dataset thresholds are tuned on. Three sinks: JSON lines on disk, in memory (tests), and
nothing. A harness with its own event log implements `Journal` in five lines.

Event schema (`kind == "decision"`):

    {"ts": "2026-09-21T10:00:00+00:00", "kind": "decision", "data": {
        "point": "routing", "provider": "jev", "model": "jev-1.13.0",
        "cost_usd": 0.0001, "input_tokens": 812, "latency_ms": 266, "error": null,
        "answers": {"complexity": {"kind": "score", "score": 0.3, "confidence": 0.9, ...}},
        "outcome": {"requested": "default", "chosen": "light", "reason": "..."}}}
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .contract import Decision


@runtime_checkable
class Journal(Protocol):
    def record(self, kind: str, data: Mapping[str, Any]) -> None: ...


class NullJournal:
    def record(self, kind: str, data: Mapping[str, Any]) -> None:
        return None


class MemoryJournal:
    """Keeps events in a list. For tests and for harnesses that flush themselves."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record(self, kind: str, data: Mapping[str, Any]) -> None:
        self._events = [*self._events, _event(kind, data)]

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def decisions(self) -> list[dict[str, Any]]:
        return [e["data"] for e in self._events if e["kind"] == "decision"]


class JsonlJournal:
    """Append-only JSON lines. One file per job is the usual layout."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def record(self, kind: str, data: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_event(kind, data), ensure_ascii=False, default=str) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _event(kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
    return {"ts": datetime.now(UTC).isoformat(), "kind": kind, "data": dict(data)}


def decision_event(decision: Decision, outcome: Mapping[str, Any]) -> dict[str, Any]:
    """The `data` of a decision event: the raw answers plus what the policy did with them."""
    return {
        "point": decision.point,
        "provider": decision.provider,
        "model": decision.model,
        "cost_usd": decision.cost_usd,
        "input_tokens": decision.input_tokens,
        "latency_ms": decision.latency_ms,
        "error": decision.error,
        "answers": {key: answer.to_dict() for key, answer in decision.answers.items()},
        "outcome": dict(outcome),
    }
