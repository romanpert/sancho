"""The provider that answers nothing. Every policy falls to its default.

It is what runs when there is no key or the squire is switched off, and it is the proof
that the harness works without the squire: worse routing, never broken.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..contract import Decision, Question, State


class NullDecider:
    name = "null"
    # It answers nothing, so it cannot answer wrongly about an attachment it did not read.
    accepts_attachments = True

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        return Decision(point=point, answers={}, provider=self.name, model="-")
