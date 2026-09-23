"""Building a knowledge graph: which chunks deserve an extraction call, and which of the
triples that come back are actually in the text.

Graph construction is the clearest case of the substitution economy in this package. A
GraphRAG-style pipeline sends *every* chunk of the corpus to a generative model to have
entities and relations pulled out of it, and then sends candidate pairs back to have
duplicates merged. Extraction has to generate, so it stays where it is. The two judgments
around it do not:

- **The gate.** Most chunks of a real corpus contain nothing the schema is looking for:
  boilerplate, navigation, legal footers, tables of contents, acknowledgements. Asking
  whether a chunk contains anything at all costs 29 millionths of a dollar; extracting from
  it costs a generative call with its output. Skipping a chunk that had something costs
  graph coverage, so the gate only skips on a confident no.
- **The edge check.** Extraction hallucinates relations that the chunk does not state, and
  a wrong edge is worse than a missing one because everything downstream believes it. The
  check is the verify-and-escalate cascade of the citation point, applied to a triple: the
  subject and object strings are matched in the text by code, and only the relation between
  them is asked of the decider.

Entity resolution, the third judgment, is already `entities.alignment_questions`, and it
is the one with a measured number (24/24 on hard pairs, paper G1).

Not yet measured against an independent annotator: `benches/graph-build.jsonl` is
single-author, and these two points are newer than the ones in the paper's Section 5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..contract import Decision, Question, Truth
from ..policy import Thresholds, confident, probability
from ..text import truncate

CHUNK_LIMIT = 1200
SCHEMA_LIMIT = 500
TRIPLE_LIMIT = 200


# --- G5: is this chunk worth an extraction call? ----------------------------------------


def gate_questions(
    *, chunk: str, looking_for: str, kinds: Sequence[str] = ()
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """`looking_for` states the extraction schema in one phrase; `kinds` names its types."""
    state: dict[str, Any] = {
        "looking_for": truncate(looking_for, SCHEMA_LIMIT),
        "chunk": truncate(chunk, CHUNK_LIMIT),
    }
    if kinds:
        state["kinds"] = [str(k) for k in kinds]
    qs: dict[str, Question] = {
        "has_anything": Truth(
            "Does `chunk` state at least one thing of the kind `looking_for` describes "
            "(`kinds` lists the types, if given): a named entity of that sort, or a relation "
            "or attribute of one?",
            criteria={
                "true": {
                    "what": "Names at least one instance and says something about it, even in "
                    "passing, even if the chunk is mostly about something else",
                    "examples": [
                        "a paragraph of a ruling that names the defendant and the sentence",
                        "a sentence of a news article that names the company and its owner",
                    ],
                },
                "false": {
                    "what": "Structural or generic text with no instance in it: navigation, "
                    "headers and footers, a table of contents, a cookie notice, boilerplate "
                    "legal text, a list of section titles, generalities about the domain",
                    "examples": [
                        "'Inicio | Noticias | Contacto | Aviso legal'",
                        "'This site uses cookies to improve your experience.'",
                        "'Defamation is regulated by law in most jurisdictions.'",
                    ],
                },
            },
        )
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Gate:
    extract: bool
    reason: str
    probability: float


def decide_gate(decision: Decision, t: Thresholds) -> Gate:
    """Skip the extraction call only on a confident no. Everything else extracts."""
    if decision.failed:
        return Gate(True, "decider unavailable: extract", 0.0)
    answer = decision.answer("has_anything")
    p = probability(answer, default=1.0)
    if answer.empty:
        return Gate(True, "no data: extract", p)
    if p <= 1.0 - t.act and confident(answer, t.act):
        return Gate(False, f"nothing of that kind ({p:.2f})", p)
    return Gate(True, f"may contain something ({p:.2f})", p)


# --- G6: does the text actually state this edge? ----------------------------------------


def edge_questions(
    *, subject: str, relation: str, obj: str, text: str
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """One reading of a candidate triple against the chunk it was extracted from."""
    state = {
        "triple": {
            "subject": truncate(subject, TRIPLE_LIMIT),
            "relation": truncate(relation, TRIPLE_LIMIT),
            "object": truncate(obj, TRIPLE_LIMIT),
        },
        "text": truncate(text, CHUNK_LIMIT),
    }
    qs: dict[str, Question] = {
        "stated": Truth(
            "Does `text` state that `triple.subject` stands in the relation "
            "`triple.relation` to `triple.object`?",
            criteria={
                "true": {
                    "what": "The text says it, in any wording, including as an apposition or "
                    "a subordinate clause",
                    "examples": [
                        "text: 'Inversiones Delta, propiedad de Mario Reyes desde 2011' for "
                        "(Mario Reyes, owns, Inversiones Delta)"
                    ],
                },
                "false": {
                    "what": "The text mentions both but does not state this relation between "
                    "them, states a different relation, states the reverse, or only makes it "
                    "plausible",
                    "examples": [
                        "text: 'Reyes declared before the court about Inversiones Delta' for "
                        "(Mario Reyes, owns, Inversiones Delta)",
                        "text: 'the parent company of Delta is Omega' for "
                        "(Delta, parent_of, Omega)",
                    ],
                },
            },
        ),
        "direction": Truth(
            "If the relation is there at all, is it in the direction the triple states, with "
            "`triple.subject` as the one that has it and `triple.object` as the one it is "
            "had towards, rather than the other way round?",
            criteria={
                "true": {"what": "The text's direction matches the triple's"},
                "false": {
                    "what": "The text states the same relation with the roles swapped",
                    "examples": [
                        "text: 'Omega is the parent of Delta' for (Delta, parent_of, Omega)"
                    ],
                },
            },
        ),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class EdgeCheck:
    verdict: str  # "supported" | "reversed" | "unsupported" | "review"
    stated: float
    direction: float
    confidence: float

    @property
    def commit(self) -> bool:
        return self.verdict == "supported"


def decide_edge(decision: Decision, t: Thresholds, *, mentions_found: bool = True) -> EdgeCheck:
    """Commit a triple only on a confident yes in the stated direction.

    `mentions_found` is code's own answer to whether both strings appear in the text at all,
    the same literal check the citation point does before spending a call. A triple whose
    subject or object is not in the chunk was invented by the extractor, and no model has
    to be asked about it.
    """
    if not mentions_found:
        return EdgeCheck("unsupported", 0.0, 0.0, 1.0)
    if decision.failed:
        return EdgeCheck("review", 0.0, 0.0, 0.0)
    stated, direction = decision.answer("stated"), decision.answer("direction")
    ps, pdir = probability(stated), probability(direction, default=1.0)
    if stated.empty:
        return EdgeCheck("review", ps, pdir, 0.0)
    if not confident(stated, t.citation):
        return EdgeCheck("review", ps, pdir, stated.confidence)
    if ps < 0.5:
        return EdgeCheck("unsupported", ps, pdir, stated.confidence)
    if not direction.empty and pdir < 0.5 and confident(direction, t.relax):
        return EdgeCheck("reversed", ps, pdir, direction.confidence)
    return EdgeCheck("supported", ps, pdir, stated.confidence)
