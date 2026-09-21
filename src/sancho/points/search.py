"""Search tier: cut a repeated query, send keyword queries to a cheap engine, keep the
model's own (paid, reformulating) search for natural-language questions.

Measured (paper, D2): 17/18. The first version asked whether "a common search engine would
find it": a prediction, 38 % agreement. Rewritten as a reading ("is it written as keywords
or as a question?") with token-overlap repetition moved into code: 94 %.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..contract import Choice, Decision, Question, Truth
from ..policy import Thresholds, probability
from ..text import truncate
from .triage import SOURCE_KINDS

Route = Literal["cut", "cheap", "full"]
PREVIOUS_LIMIT = 20

# Which category of a meta-search engine (SearXNG) serves each source kind.
CHEAP_CATEGORIES: dict[str, str] = {"news": "news", "academic": "science", "social": "social media"}


def questions(
    query: str, *, previous: Sequence[str] = (), brief: str = ""
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {
        "query": truncate(query, 300),
        "previous_queries": [truncate(q, 200) for q in list(previous)[-PREVIOUS_LIMIT:]],
        "brief": truncate(brief, 400),
    }
    qs: dict[str, Question] = {
        "redundant": Truth(
            "Is `query` asking for the same thing as one of `previous_queries`: same entities "
            "and same information need, even if the words differ or are synonyms?",
            {
                "true": {
                    "what": "Same entities and same need, reworded, translated or with synonyms",
                    "examples": [
                        "'sismo Oaxaca marzo 2026 magnitud' after "
                        "'terremoto Oaxaca 12 marzo 2026 magnitud'",
                        "'ley 6132 texto' after 'texto de la ley 6132 sobre expresion'",
                    ],
                },
                "false": {
                    "what": "A new entity, a new time window, a new document type or a new angle",
                    "examples": [
                        "'sismo Oaxaca marzo 2026 viviendas danadas' after "
                        "'sismo Oaxaca marzo 2026 magnitud'",
                    ],
                },
            },
        ),
        "source_kind": Choice(
            "Which kind of source is `query` most likely trying to reach?", SOURCE_KINDS
        ),
        "keyword_query": Truth(
            "Is `query` written as search keywords (names, terms, numbers, dates, a site or "
            "document name), rather than as a full natural-language question or a request "
            "with several parts?",
            {
                "true": {
                    "what": "Keywords or a short noun phrase a person would type into a search box",
                    "examples": [
                        "sismo Oaxaca marzo 2026 magnitud",
                        "ley 6132 expresion difusion pensamiento pdf",
                        "sentencia TC/0075/16 tribunal constitucional",
                    ],
                },
                "false": {
                    "what": "A full question, or a request that combines conditions, "
                    "comparisons or a time range with an outcome",
                    "examples": [
                        "que sentencias del Tribunal Constitucional entre 2020 y 2026 citan el "
                        "articulo 49 al resolver querellas contra periodistas y con que resultado"
                    ],
                },
            },
        ),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class SearchRoute:
    route: Route
    category: str
    reason: str
    keyword_probability: float
    redundant_probability: float


def decide(
    decision: Decision,
    t: Thresholds,
    *,
    cheap_available: bool,
    repeat_by_code: bool = False,
) -> SearchRoute:
    """Where a query goes. `repeat_by_code` comes from token overlap computed before the call."""
    if decision.failed:
        if repeat_by_code:
            return SearchRoute("cut", "general", "repeated query (token overlap)", 0.0, 1.0)
        return SearchRoute("full", "general", "decider unavailable", 0.0, 0.0)
    redundant_p = probability(decision.answer("redundant"))
    keyword_p = probability(decision.answer("keyword_query"))
    kind = decision.answer("source_kind").choice or "other"
    category = CHEAP_CATEGORIES.get(kind, "general")
    if repeat_by_code or redundant_p >= t.redundant:
        return SearchRoute("cut", category, "query repeats an earlier one", keyword_p, redundant_p)
    if cheap_available and keyword_p >= t.keyword:
        return SearchRoute(
            "cheap", category, f"keyword query ({keyword_p:.2f})", keyword_p, redundant_p
        )
    return SearchRoute(
        "full", category, f"natural-language question ({keyword_p:.2f})", keyword_p, redundant_p
    )
