"""Your own models as a decider: a classifier, an embedding similarity, a vision model.

A `LocalDecider` is a mapping from question keys to handlers. A handler receives the state
and the question and returns an `Answer` (use `sanchopanza.answers` to build one) or `None` when
it cannot answer that question. Handlers may be sync or async. Unanswered questions stay
empty, and the policies use their defaults for them: partial coverage is fine.

This is the destination the paper points to: a hosted decision model to start with no
labelled data, a journal of every decision as the dataset, and a local model behind the
same contract once there are labels. Nothing above this file changes when that happens.

Example: a sklearn classifier for the `injection` question and Jev for everything else.

    local = LocalDecider({"injection": lambda state, q: answers.truth(clf.predict_proba(...))})
    squire = Squire(FallbackDecider([local, jev]))

A vision model plugs in the same way: put the image reference in the state, write a
handler that reads it, and return `answers.choice({...})` or `answers.truth(p)`.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..contract import Answer, Decision, Question, State

Handler = Callable[[State, Question], Answer | None | Awaitable[Answer | None]]
WILDCARD = "*"


class LocalDecider:
    name = "local"
    # Handlers receive the state untouched, so whatever they can read, they can read.
    accepts_attachments = True

    def __init__(
        self,
        handlers: Mapping[str, Handler] | Handler,
        *,
        model: str = "local",
        cost_usd_per_call: float = 0.0,
    ) -> None:
        self._handlers: Mapping[str, Handler] = (
            handlers if isinstance(handlers, Mapping) else {WILDCARD: handlers}
        )
        self._model = model
        self._cost = cost_usd_per_call

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        answers: dict[str, Answer] = {}
        for key, question in questions.items():
            handler = self._handlers.get(key) or self._handlers.get(WILDCARD)
            if handler is None:
                continue
            result: Any = handler(state, question)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, Answer) and not result.empty:
                answers[key] = result
        return Decision(
            point=point,
            answers=answers,
            provider=self.name,
            model=self._model,
            cost_usd=self._cost if answers else 0.0,
        )
