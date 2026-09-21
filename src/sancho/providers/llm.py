"""Any LLM as a decider, with output forced into a JSON schema built from the questions.

This is the baseline of the paper (Claude Haiku 4.5, tool-forced output) turned into a
provider. It exists for three reasons: to compare a System One model against a small LLM
on the same questions, to serve as the fallback when no decision model is available, and
to show that the contract does not depend on any vendor.

The important caveat is measured, not assumed: an LLM's confidence is **self-reported**,
and in our runs 9 of its 17 errors carried confidence >= 0.75. Policies still apply the
same thresholds, but the journal records `provider="llm"` so the trace says which kind of
confidence it was.

`complete(system, user, schema) -> (payload, input_tokens, output_tokens)` is the only
thing a vendor adapter has to provide. Two are included: Anthropic Messages (tool-forced)
and OpenAI Chat Completions (json_schema). Both use httpx; neither pulls in an SDK.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .. import answers as make
from ..contract import (
    Answer,
    Choice,
    DeciderUnavailable,
    Decision,
    Question,
    Score,
    State,
    Truth,
)

Completion = tuple[Mapping[str, Any] | None, int, int]
Completer = Callable[[str, str, dict[str, Any]], Awaitable[Completion]]

SYSTEM = (
    "You are a classifier inside an agent harness. Read `state` and answer every question "
    "through the schema. Do not explain."
)


def schema_for(question: Question) -> dict[str, Any]:
    if isinstance(question, Choice):
        return {"type": "string", "enum": list(question.options)}
    if isinstance(question, Score):
        return {"type": "integer", "minimum": 0, "maximum": len(question.levels) - 1}
    return {"type": "boolean"}


def description_for(question: Question) -> str:
    if isinstance(question, Truth):
        body: dict[str, Any] = {"question": question.instructions, "criteria": question.criteria}
    elif isinstance(question, Choice):
        body = {"question": question.instructions, "options": dict(question.options)}
    else:
        body = {"question": question.instructions, "levels": list(question.levels)}
    return json.dumps(body, ensure_ascii=False, default=str)


def build_schema(questions: Mapping[str, Question]) -> dict[str, Any]:
    properties = {
        key: {**schema_for(q), "description": description_for(q)} for key, q in questions.items()
    }
    properties["confidence"] = {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "description": "Your confidence in the answers, 0 to 1",
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def answers_from(
    payload: Mapping[str, Any], questions: Mapping[str, Question]
) -> dict[str, Answer]:
    """Map a schema-shaped payload to contract answers, reusing the policies unchanged."""
    confidence = float(payload.get("confidence", 0.5) or 0.5)
    out: dict[str, Answer] = {}
    for key, question in questions.items():
        value = payload.get(key)
        if isinstance(question, Truth) and isinstance(value, bool):
            out[key] = make.truth(confidence if value else 1.0 - confidence)
        elif isinstance(question, Choice) and value in question.options:
            out[key] = make.labelled(str(value), list(question.options), confidence=confidence)
        elif isinstance(question, Score) and isinstance(value, int) and not isinstance(value, bool):
            out[key] = Answer(kind="score", score=float(value), confidence=confidence)
    return out


class LLMDecider:
    name = "llm"

    def __init__(
        self,
        complete: Completer,
        *,
        model: str = "llm",
        price_in_per_mtok: float = 0.0,
        price_out_per_mtok: float = 0.0,
    ) -> None:
        self._complete = complete
        self._model = model
        self._price_in = price_in_per_mtok
        self._price_out = price_out_per_mtok

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        user = "state:\n" + json.dumps(state, ensure_ascii=False, default=str)
        start = time.monotonic()
        try:
            payload, tokens_in, tokens_out = await self._complete(
                SYSTEM, user, build_schema(questions)
            )
        except Exception as error:  # a vendor error must never stop the harness
            raise DeciderUnavailable(f"llm failed: {error.__class__.__name__}") from error
        latency = int((time.monotonic() - start) * 1000)
        cost = (tokens_in * self._price_in + tokens_out * self._price_out) / 1_000_000
        return Decision(
            point=point,
            answers=answers_from(payload or {}, questions),
            provider=self.name,
            model=self._model,
            input_tokens=tokens_in,
            cost_usd=cost,
            latency_ms=latency,
        )


def anthropic_completer(
    api_key: str,
    model: str,
    *,
    base_url: str = "https://api.anthropic.com",
    timeout_s: float = 30.0,
) -> Completer:
    """Anthropic Messages API with a forced tool call, so the output is always the schema."""
    import httpx

    client = httpx.AsyncClient(
        base_url=base_url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        timeout=timeout_s,
    )

    async def complete(system: str, user: str, schema: dict[str, Any]) -> Completion:
        body = {
            "model": model,
            "max_tokens": 300,
            "system": system,
            "tools": [{"name": "answer", "description": "Typed answers", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": "answer"},
            "messages": [{"role": "user", "content": user}],
        }
        response = await client.post("/v1/messages", json=body)
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        tokens = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        for block in data.get("content") or []:
            if block.get("type") == "tool_use":
                return (block.get("input") or {}), *tokens
        return None, *tokens

    return complete


def openai_completer(
    api_key: str, model: str, *, base_url: str = "https://api.openai.com", timeout_s: float = 30.0
) -> Completer:
    """OpenAI Chat Completions with `response_format: json_schema` (strict)."""
    import httpx

    client = httpx.AsyncClient(
        base_url=base_url,
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        timeout=timeout_s,
    )

    async def complete(system: str, user: str, schema: dict[str, Any]) -> Completion:
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": schema},
            },
        }
        response = await client.post("/v1/chat/completions", json=body)
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        tokens = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        try:
            content = data["choices"][0]["message"]["content"]
            return json.loads(content), *tokens
        except (KeyError, IndexError, ValueError, TypeError):
            return None, *tokens

    return complete
