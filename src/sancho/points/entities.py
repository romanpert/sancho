"""Knowledge-graph hygiene: same entity, fact relation, closed-vocabulary classification.

Measured (paper, G1, G2, G4): entity alignment 24/24 with hard negatives (siblings, similar
nicknames, ruling vs ruling); fact relation 16/20 (not integrated in production until a
larger bench); classification against independent labels 80-85 % over majority baselines
of 43-62 %. Confusions concentrate between adjacent classes.

Classification always adds an `other` option unless told not to. The model cannot abstain
out-of-domain if the list does not let it; the paper's public-bench run measures the
effect of that option (docs/paper.md, Section 5.9).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ..contract import Choice, Decision, Question, Truth
from ..policy import Thresholds, probability
from ..text import truncate

OTHER = "other"
OTHER_DESCRIPTION = "None of the listed categories fits, or the text does not say"


def alignment_questions(
    *, a: str, context_a: str = "", b: str, context_b: str = ""
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {
        "a": {"mention": truncate(a, 200), "context": truncate(context_a, 400)},
        "b": {"mention": truncate(b, 200), "context": truncate(context_b, 400)},
    }
    qs: dict[str, Question] = {
        "same_entity": Truth(
            "Do `a.mention` and `b.mention`, read with their contexts, refer to the same "
            "real-world entity (the same person, organization, law, ruling or place)?",
            {
                "true": {
                    "what": "Same entity under a different form: alias, nickname, short or "
                    "full name, acronym, with or without a title or date",
                    "examples": [
                        "'Dario Pena, el Sabueso' and 'Dario Ernesto Pena Castillo'",
                        "'SGC' and 'Servicio Geologico Colombiano'",
                        "'Ley 6132' and "
                        "'Ley 6132 de 1962 sobre Expresion y Difusion del Pensamiento'",
                    ],
                },
                "false": {
                    "what": "Different entities, even if related: relatives with the same "
                    "surname, a person and their employer, a ruling and another ruling, a "
                    "town and the region that contains it, similar nicknames",
                    "examples": [
                        "'La Chispa' and 'La Chispita' (two different communicators)",
                        "'TC/1148/25' and 'TC/1652/25'",
                        "'San Jose del Palmar' and 'Choco'",
                    ],
                },
            },
        )
    }
    return state, qs


def decide_alignment(decision: Decision, t: Thresholds) -> tuple[bool | None, float]:
    """(same?, probability). None inside the grey zone: not sure is a valid answer."""
    answer = decision.answer("same_entity")
    p = probability(answer, default=0.5)
    if decision.failed or answer.empty or t.entity_low < p < t.entity_high:
        return None, p
    return p >= t.entity_high, p


FactRelation = Literal["agree", "conflict", "unrelated"]


def fact_questions(*, fact_a: str, fact_b: str) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {"fact_a": truncate(fact_a, 500), "fact_b": truncate(fact_b, 500)}
    qs: dict[str, Question] = {
        "relation": Choice(
            "How do `fact_a` and `fact_b` relate?",
            {
                "agree": {
                    "what": "Both can be true at once and talk about the same thing; one may "
                    "add detail to the other",
                    "examples": [
                        "'1,240 homes damaged' and '312 homes with severe structural damage'"
                    ],
                },
                "conflict": {
                    "what": "They cannot both be true as stated: different value for the same "
                    "attribute (date, amount, count, outcome, depth), or opposite outcomes",
                    "examples": [
                        "'ruling dated 7 November 2025' and 'ruling dated 18 November 2025'",
                        "'depth 110 km (USGS)' and 'depth 103 km (SGC)'",
                    ],
                },
                "unrelated": {
                    "what": "They talk about different attributes or different things and "
                    "neither supports nor contradicts the other"
                },
            },
        )
    }
    return state, qs


def decide_facts(decision: Decision, t: Thresholds) -> tuple[FactRelation | None, float]:
    answer = decision.answer("relation")
    if decision.failed or answer.empty or answer.confidence < t.relax:
        return None, answer.confidence
    choice = answer.choice if answer.choice in ("agree", "conflict", "unrelated") else None
    return choice, answer.confidence  # type: ignore[return-value]


def classification_questions(
    *,
    field: str,
    text: str,
    options: Mapping[str, Any],
    context: str = "",
    add_other: bool = True,
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """Free text to one closed category. `options` maps name to description."""
    state: dict[str, Any] = {"field": field, "text": truncate(text, 600)}
    if context:
        state["context"] = truncate(context, 800)
    opts = dict(options)
    if add_other and OTHER not in opts:
        opts[OTHER] = OTHER_DESCRIPTION
    qs: dict[str, Question] = {
        "category": Choice(
            f"Which category of `{field}` does `text` (with `context`, if present) belong to?",
            opts,
        )
    }
    return state, qs


def decide_classification(
    decision: Decision, t: Thresholds, *, options: Mapping[str, Any]
) -> tuple[str | None, float, dict[str, float]]:
    """(category, probability, distribution). None below `classify` or when `other` wins."""
    answer = decision.answer("category")
    dist = dict(answer.probabilities)
    p = dist.get(answer.choice or "", answer.confidence if answer.choice else 0.0)
    if decision.failed or answer.empty or answer.choice not in options or p < t.classify:
        return None, p, dist
    return answer.choice, p, dist
