"""Deciders that cost nothing: replay a recording, or record a real one.

- `RecordedDecider` answers from a file of recorded decisions. Dry runs and tests: no
  network call, deterministic.
- `RecordingDecider` wraps a real decider and appends every decision to a file, turning a
  real run into a reproducible fixture.

File format, one JSON object per line:

    {"key": "<sha256 prefix>", "point": "routing", "model": "jev-1.13.0", "default": false,
     "input_tokens": 812, "cost_usd": 0.000034, "latency_ms": 266,
     "answers": {"complexity": {"kind": "score", "score": 0.3, "confidence": 0.9, ...}}}

`key` identifies exactly (point, state, questions). Without an exact match, the first
entry flagged `default` for the same point is used; without that, no answer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..contract import Answer, Decider, Decision, Question, State


def key_of(point: str, state: State, questions: Mapping[str, Question]) -> str:
    """Stable fingerprint of one query. Same questions on the same state, same key."""
    body = {
        "point": point,
        "state": state,
        "questions": {k: asdict(q) for k, q in questions.items()},
    }
    serialized = json.dumps(body, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


class RecordedDecider:
    name = "recorded"

    def __init__(self, entries: Sequence[Mapping[str, Any]]) -> None:
        exact: dict[str, Mapping[str, Any]] = {}
        defaults: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            key = entry.get("key")
            point = str(entry.get("point", ""))
            if key:
                exact[str(key)] = entry
            if entry.get("default") and point not in defaults:
                defaults[point] = entry
        self._exact = exact
        self._defaults = defaults

    @classmethod
    def from_file(cls, path: Path | str) -> RecordedDecider:
        path = Path(path)
        if not path.exists():
            return cls(())
        lines = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(lines)

    def __len__(self) -> int:
        return len(self._exact)

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        entry = self._exact.get(key_of(point, state, questions)) or self._defaults.get(point)
        if entry is None:
            return Decision(point=point, answers={}, provider=self.name, model="-")
        answers = {
            key: Answer.from_dict(value)
            for key, value in (entry.get("answers") or {}).items()
            if key in questions
        }
        return Decision(
            point=point,
            answers=answers,
            provider=self.name,
            model=str(entry.get("model") or "recorded"),
            input_tokens=int(entry.get("input_tokens") or 0),
            cost_usd=float(entry.get("cost_usd") or 0.0),
            latency_ms=int(entry.get("latency_ms") or 0),
        )


class RecordingDecider:
    """Wraps a real decider and writes each decision down, ready to be replayed."""

    def __init__(self, inner: Decider, path: Path | str) -> None:
        self._inner = inner
        self._path = Path(path)
        self.name = inner.name

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        decision = await self._inner.decide(point, state, questions)
        line = {
            "key": key_of(point, state, questions),
            "point": point,
            "model": decision.model,
            "default": False,
            "input_tokens": decision.input_tokens,
            "cost_usd": decision.cost_usd,
            "latency_ms": decision.latency_ms,
            "answers": {k: a.to_dict() for k, a in decision.answers.items()},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return decision
