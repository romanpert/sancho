"""Composition: several deciders behind one contract.

- `FallbackDecider([a, b, c])`: ask `a`; if it is unavailable or answers nothing, ask `b`,
  and so on. Answers from different providers are merged question by question, so a local
  model can cover two questions and a hosted one the rest.
- `RoutedDecider({"guard": local, "citation": jev}, default=jev)`: one provider per
  decision point. The way to keep a sensitive point on-premise and the rest hosted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..contract import Decider, DeciderUnavailable, Decision, Question, State


class FallbackDecider:
    def __init__(self, deciders: Sequence[Decider]) -> None:
        if not deciders:
            raise ValueError("a fallback chain needs at least one decider")
        self._deciders = list(deciders)
        self.name = "fallback(" + ">".join(d.name for d in deciders) + ")"

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        merged: dict = {}
        providers: list[str] = []
        tokens = cost = latency = 0
        model = "-"
        errors: list[str] = []
        for decider in self._deciders:
            pending = {k: q for k, q in questions.items() if k not in merged}
            if not pending:
                break
            try:
                decision = await decider.decide(point, state, pending)
            except DeciderUnavailable as error:
                errors.append(f"{decider.name}: {error}")
                continue
            if decision.answers:
                merged = {**merged, **decision.answers}
                providers.append(decision.provider)
                model = decision.model if model == "-" else model
            tokens += decision.input_tokens
            cost += decision.cost_usd
            latency += decision.latency_ms
        if not merged and errors and len(errors) == len(self._deciders):
            raise DeciderUnavailable("; ".join(errors))
        return Decision(
            point=point,
            answers=merged,
            provider="+".join(providers) or self.name,
            model=model,
            input_tokens=tokens,
            cost_usd=cost,
            latency_ms=latency,
        )


class RoutedDecider:
    def __init__(self, by_point: Mapping[str, Decider], default: Decider) -> None:
        self._by_point = dict(by_point)
        self._default = default
        self.name = "routed"

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        return await self._by_point.get(point, self._default).decide(point, state, questions)
