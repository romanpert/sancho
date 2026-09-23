"""Sancho: a calibrated, non-generative decision layer for LLM agent harnesses.

The knight thinks; the squire reads. A System One decision model (TypeSafe's Jev, a local
classifier, an LLM forced into a schema) takes the procedural decisions of an agent loop
(which model, which search, which page, which citation, which command) through the
harness's hooks and tools, with calibrated probabilities, asymmetric thresholds, fail-open
defaults and a journal entry for every decision.

    from sanchopanza import Squire, Thresholds
    from sanchopanza.providers import create

    squire = Squire(create("jev"), thresholds=Thresholds())
    tier = await squire.route_task("List the rulings that mention defamation since 2020")
"""

from .answers import choice, labelled, score, truth
from .budget import Meter
from .contract import (
    Answer,
    Choice,
    Decider,
    DeciderUnavailable,
    Decision,
    Question,
    Score,
    State,
    Truth,
)
from .journal import JsonlJournal, MemoryJournal, NullJournal
from .policy import Thresholds
from .squire import GuardResult, Squire

__version__ = "0.2.0"

__all__ = [
    "Answer",
    "Choice",
    "Decider",
    "DeciderUnavailable",
    "Decision",
    "GuardResult",
    "JsonlJournal",
    "MemoryJournal",
    "Meter",
    "NullJournal",
    "Question",
    "Score",
    "Squire",
    "State",
    "Thresholds",
    "Truth",
    "__version__",
    "choice",
    "labelled",
    "score",
    "truth",
]
