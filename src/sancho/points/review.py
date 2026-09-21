"""Thread review: when a delegated subtask returns, did it answer, is the line exhausted,
does it state facts without sources?

Measured (paper, D6 and E2): unsourced-claim detection 21/22, AUC 1.00. This is the
"evaluate" step of the loop done by a model that did not reason and cannot write, so it
cannot prefer its own text. It speaks only when a signal is strong (>= `review`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..contract import Decision, Question, Truth
from ..policy import Thresholds
from ..text import truncate

TASK_LIMIT = 1200
RESULT_LIMIT = 2500


def questions(task: str, result: str) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {"task": truncate(task, TASK_LIMIT), "result": truncate(result, RESULT_LIMIT)}
    qs: dict[str, Question] = {
        "answered": Truth(
            "Does `result` answer `task` with specific findings that name their sources?"
        ),
        "saturated": Truth(
            "Does `result` indicate that the line is exhausted: no further sources exist or "
            "nothing more can be found?"
        ),
        "unsourced": Truth(
            "Does `result` state specific facts (figures, dates, names, outcomes) without "
            "naming a concrete source for them: a URL, a document title or number, a "
            "publication with date, or a file where the sourced list lives?",
            {
                "true": {
                    "what": "Specific facts with no source, or with vague attributions only",
                    "examples": [
                        "segun expertos, la profundidad explica...",
                        "distintas fuentes dan cifras algo diferentes",
                        "fue una decision muy comentada en redes",
                    ],
                },
                "false": {
                    "what": "Each fact carries a concrete source, or the result declares "
                    "that it could not confirm and gives no unsourced figure",
                    "examples": [
                        "segun el boletin de Proteccion Civil del 14 de marzo (url)",
                        "ordinal TERCERO de la sentencia, p. 39 del PDF oficial",
                        "no he podido confirmar la cifra; declaro la linea incompleta",
                    ],
                },
            },
        ),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Review:
    answered: float
    saturated: float
    unsourced: float
    notes: tuple[str, ...]

    @property
    def message(self) -> str | None:
        if not self.notes:
            return None
        return (
            f"Thread review (decision model): answered {self.answered:.2f}, "
            f"exhausted {self.saturated:.2f}, unsourced {self.unsourced:.2f}. "
            + "; ".join(self.notes)
            + "."
        )


def decide(decision: Decision, t: Thresholds) -> Review | None:
    """A short note for the orchestrator, or nothing when there is no signal."""
    if decision.failed:
        return None
    answered = decision.answer("answered").truth
    saturated = decision.answer("saturated").truth
    unsourced = decision.answer("unsourced").truth
    if answered is None or saturated is None or unsourced is None:
        return None
    notes: list[str] = []
    if unsourced >= t.review:
        notes.append("it states facts without sources: do not cite them until sourced")
    if saturated >= t.review:
        notes.append("the line looks exhausted: do not reopen it without new data")
    if answered <= 1.0 - t.review:
        notes.append("it does not answer what was asked: rethink the task before retrying")
    return Review(answered, saturated, unsourced, tuple(notes))
