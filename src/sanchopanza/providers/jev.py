"""TypeSafe Jev over its native HTTP API. One file, no SDK: the wire format fits in 60 lines.

    POST https://api.typesafe.ai/v1/systemone
    Authorization: Bearer $TYPESAFE_API_KEY
    {"model": "jev-latest", "state": ..., "questions": {id: {"type", "instructions", "criteria"}}}

Price (2026-09): 0.042 USD per million input tokens, output free. The price is a
constructor argument, not a constant, so a change is configuration, not code.
The model defaults to a pinned version rather than an alias: see DEFAULT_MODEL.
Retries: 429 and 529 with bounded exponential backoff. No unbounded loops.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Mapping
from typing import Any

from ..contract import (
    Answer,
    Choice,
    DeciderUnavailable,
    Decision,
    Question,
    Score,
    State,
    Truth,
    truth_confidence,
)
from ..media import attachments_in

BASE_URL = "https://api.typesafe.ai"
PATH = "/v1/systemone"
# **Pinned, not an alias, and the vendor says to pin.** Their own model page: "An alias
# moves when a new release ships, so the answers behind it can change without a change on
# your side... If you have tuned confidence thresholds against a specific version, pin
# that version's ID instead of the alias and move to the new one on your own schedule."
# This package is nothing but tuned thresholds, and a non-generative model gives no
# "the output looks odd" signal when it moves: no error, no failing test, no log line.
# This is the version every number in docs/paper.md was measured against. Pass
# `model="jev-latest"` deliberately if you want to track the alias.
DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_PRICE_PER_MTOK = 0.042

KIND_TO_WIRE = {"choice": "choice", "score": "score", "truth": "noul"}
WIRE_TO_KIND = {v: k for k, v in KIND_TO_WIRE.items()}
RETRYABLE = frozenset({429, 529})
MAX_RETRIES = 3
BASE_WAIT_S = 0.25


def to_wire(question: Question) -> dict[str, Any]:
    """Contract question to TypeSafe request format."""
    if isinstance(question, Choice):
        return {
            "type": "choice",
            "instructions": question.instructions,
            "criteria": dict(question.options),
        }
    if isinstance(question, Score):
        return {
            "type": "score",
            "instructions": question.instructions,
            "criteria": list(question.levels),
        }
    if isinstance(question, Truth):
        body: dict[str, Any] = {"type": "noul", "instructions": question.instructions}
        if question.criteria:
            body["criteria"] = dict(question.criteria)
        return body
    raise TypeError(f"unknown question type: {type(question)!r}")


def from_wire(raw: Mapping[str, Any]) -> Answer:
    """TypeSafe answer to contract. Tolerates missing fields."""
    kind = WIRE_TO_KIND.get(str(raw.get("type", "")), "truth")
    probabilities = {str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()}
    if kind == "truth":
        value = raw.get("noul")
        truth = float(value) if value is not None else None
        return Answer(
            kind="truth",
            confidence=truth_confidence(truth) if truth is not None else 0.0,
            truth=truth,
        )
    confidence = float(raw.get("confidence") or 0.0)
    if kind == "choice":
        chosen = raw.get("choice")
        return Answer(
            kind="choice",
            confidence=confidence,
            choice=str(chosen) if chosen is not None else None,
            probabilities=probabilities,
        )
    value = raw.get("score")
    return Answer(
        kind="score",
        confidence=confidence,
        score=float(value) if value is not None else None,
        probabilities=probabilities,
    )


class JevDecider:
    """Async client for Jev. One instance per job; it reuses the connection."""

    name = "jev"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        model: str = DEFAULT_MODEL,
        price_per_mtok: float = DEFAULT_PRICE_PER_MTOK,
        timeout_s: float = 10.0,
        client: Any | None = None,
    ) -> None:
        key = api_key or os.environ.get("TYPESAFE_API_KEY", "")
        if not key:
            raise DeciderUnavailable("TYPESAFE_API_KEY is not set")
        try:
            import httpx
        except ImportError as error:  # pragma: no cover - exercised only without the extra
            raise DeciderUnavailable("install sancho[jev] to use the Jev provider") from error
        self._model = model
        self._price = price_per_mtok
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=timeout_s,
        )
        self._httpx = httpx

    async def aclose(self) -> None:
        await self._client.aclose()

    accepts_attachments = False

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        found = attachments_in(state)
        if found:
            # Refuse loudly. The alternative, sending the state with the attachment stripped
            # out, returns a confident answer to a question about something the model never
            # saw, which is worse than no answer: the squire's fail-open turns this into the
            # harness default and journals the reason. Route the point to a provider that
            # reads images (RoutedDecider) or put one in front (FallbackDecider).
            kinds = ", ".join(sorted({a.media_type for a in found}))
            raise DeciderUnavailable(
                f"this model accepts text only and the state carries {len(found)} "
                f"attachment(s) ({kinds}); its own documentation says images, audio and "
                "video are not supported"
            )
        body = {
            "model": self._model,
            "state": state,
            "questions": {key: to_wire(q) for key, q in questions.items()},
        }
        start = time.monotonic()
        data = await self._send(body)
        latency_ms = int((time.monotonic() - start) * 1000)
        answers = {key: from_wire(value) for key, value in (data.get("answers") or {}).items()}
        tokens = int((data.get("usage") or {}).get("input_tokens") or 0)
        return Decision(
            point=point,
            answers=answers,
            provider=self.name,
            model=str(data.get("model") or self._model),
            input_tokens=tokens,
            cost_usd=tokens * self._price / 1_000_000,
            latency_ms=latency_ms,
        )

    async def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        last = "no response"
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._client.post(PATH, json=body)
            except self._httpx.HTTPError as error:
                raise DeciderUnavailable(f"jev unreachable: {error.__class__.__name__}") from error
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as error:
                    raise DeciderUnavailable("jev returned a non-JSON body") from error
            last = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE or attempt == MAX_RETRIES:
                break
            await asyncio.sleep(BASE_WAIT_S * (2**attempt))
        raise DeciderUnavailable(f"jev did not answer: {last}")
