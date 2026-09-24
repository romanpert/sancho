"""Agent memory: what to write down, what it collides with, and when to go looking.

A memory pipeline is three judgments per fact, and today every one of them is an LLM call:
*is this worth storing*, *does it collide with something already stored*, and, per turn,
*do we even need to look*. They are classification-shaped: the answer is a yes, a no or one
label out of four. Nothing has to be written, so nothing here needs a model that can write.

The three asymmetries are not the same, and getting them backwards is how a memory rots:

- **Writing** is the costly direction. A junk memory is read on every later turn, for free
  to the model that wrote it and at a price to every one after. Storing needs `act`.
- **Forgetting** is the costly direction too, and it is worse, because it is silent. Dropping
  or replacing a stored fact needs `act`; in doubt both are kept and the collision is flagged.
- **Recall** is the opposite. Skipping a lookup that was needed costs an answer; making one
  that was not needed costs a few hundred tokens. So a lookup happens unless the decider is
  confidently sure it is pointless.

**Code before model, and it matters more here than anywhere else.** Which of two facts is
newer is a timestamp comparison, and this model class reads dates as text (paper, 5.3). So
the decider is never asked *which one wins*. It is asked whether they speak about the same
attribute of the same thing and whether they can both be true; recency comes from the
harness's own metadata, and when the harness does not know, the collision is flagged for a
human instead of resolved by a guess.

Not yet measured against an independent annotator: `benches/memory.jsonl` is single-author,
like the rest, and these three points are newer than the ones in the paper's Section 5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..contract import Decision, Question, Truth
from ..policy import Thresholds, probability
from ..text import truncate

FACT_LIMIT = 500
CONTEXT_LIMIT = 400
TURN_LIMIT = 600
TOPICS_LIMIT = 500


# --- M1: is this worth storing? ---------------------------------------------------------


def write_questions(
    *, fact: str, brief: str = "", source: str = ""
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """Three readings of a candidate memory. None of them asks the model to value it."""
    state: dict[str, Any] = {"fact": truncate(fact, FACT_LIMIT)}
    if brief:
        state["brief"] = truncate(brief, CONTEXT_LIMIT)
    if source:
        state["source"] = truncate(source, CONTEXT_LIMIT)
    qs: dict[str, Question] = {
        "durable": Truth(
            "Will `fact` still be true and still matter after the current task is finished?",
            criteria={
                "true": {
                    "what": "A stable property of a person, organization, case or system; a "
                    "decision taken and why; a constraint, preference or rule that will apply "
                    "again",
                    "examples": [
                        "the registry only serves rulings from 2018 onward",
                        "the client asked for the report in Spanish",
                        "we ruled out the 2019 case: different defendant with the same name",
                    ],
                },
                "false": {
                    "what": "State of the current step, a transient value, a plan for the next "
                    "few minutes, or a restatement of the task that was just given",
                    "examples": [
                        "we are on search number four",
                        "the page is loading slowly today",
                        "the user asked us to investigate this company",
                    ],
                },
            },
        ),
        "specific": Truth(
            "Is `fact` concrete enough to be used later without going back to the source: "
            "does it name things, figures, dates or outcomes rather than describe them?",
            criteria={
                "true": {
                    "what": "Names the entity and states the value, outcome or reason",
                    "examples": [
                        "TC/1148/25 annulled articles 34, 35 and 36 of Ley 6132",
                        "the parent company is registered in Panama since 2011",
                    ],
                },
                "false": {
                    "what": "A generality, a summary of the obvious, or a pointer with no content",
                    "examples": [
                        "there is relevant information about the company",
                        "defamation law has changed over the years",
                    ],
                },
            },
        ),
        "derivable": Truth(
            "Could `fact` be recovered at any time, cheaply and exactly, by re-reading a "
            "source the agent already has (`source`, a file, a record it can query again)?",
            criteria={
                "true": {
                    "what": "It is a verbatim copy of, or a direct lookup in, something "
                    "durable and reachable: a file in the repository, a row in the database, "
                    "a document already downloaded",
                    "examples": [
                        "the function is defined in agent/harness/motor.py",
                        "the ruling's text says '500,000 pesos' in its third page",
                    ],
                },
                "false": {
                    "what": "It is a conclusion, a reconciliation between sources, a negative "
                    "result, or something the agent learned by doing and would have to redo",
                    "examples": [
                        "the two registries disagree on the depth; the official one is SGC",
                        "the portal rejects requests without a referer header",
                    ],
                },
            },
        ),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Write:
    store: bool
    reason: str
    durable: float
    specific: float
    derivable: float


def decide_write(decision: Decision, t: Thresholds) -> Write:
    """Store only on an explicit, confident yes. No data means the harness's default."""
    if decision.failed:
        return Write(False, "decider unavailable: harness default", 0.0, 0.0, 0.0)
    durable, specific = decision.answer("durable"), decision.answer("specific")
    derivable = decision.answer("derivable")
    pd, ps, pr = probability(durable), probability(specific), probability(derivable)
    if durable.empty or specific.empty:
        return Write(False, "no data: harness default", pd, ps, pr)
    if pd < t.remember:
        return Write(False, f"not durable ({pd:.2f})", pd, ps, pr)
    if ps < t.remember:
        return Write(False, f"not specific enough ({ps:.2f})", pd, ps, pr)
    if pr > t.act:
        return Write(False, f"re-readable from the source ({pr:.2f})", pd, ps, pr)
    return Write(True, f"durable {pd:.2f}, specific {ps:.2f}", pd, ps, pr)


# --- M2: does it collide with what is already stored? -----------------------------------

Collision = Literal["duplicate", "replace", "flag", "keep_both"]


def collision_questions(*, new: str, stored: str) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """Two readings. Neither of them is 'which one is right', and neither is about dates.

    The first question asks for a *contradiction*, not for a shared attribute. Two facts can
    describe the same field and agree (a second source giving the same figure), and the
    first draft of this point asked only whether the attribute was shared, which sent every
    corroboration to a human as if it were a conflict. Corroboration is the common case in
    an investigation, so that draft would have made the collision check useless.
    """
    state = {"new": truncate(new, FACT_LIMIT), "stored": truncate(stored, FACT_LIMIT)}
    qs: dict[str, Question] = {
        "contradicts": Truth(
            "Do `new` and `stored` state values for the same attribute of the same thing "
            "that cannot both be true at once: a different figure, date, status or outcome "
            "for the same field of the same entity?",
            criteria={
                "true": {
                    "what": "Same entity, same field, incompatible values",
                    "examples": [
                        "'the case is on appeal' and 'the case was closed in 2024'",
                        "'depth 110 km' and 'depth 103 km', both of the same earthquake",
                    ],
                },
                "false": {
                    "what": "Different entities, different fields, or the same field with "
                    "values that can both hold, including the same value from another source "
                    "or a narrower version of the same one",
                    "examples": [
                        "'1,240 homes damaged' and '312 of them structurally severe'",
                        "'registered in Panama' and 'the director resigned in 2022'",
                        "'1,240 homes, per the newspaper' and '1,240 homes, per the bulletin'",
                    ],
                },
            },
        ),
        "adds_nothing": Truth(
            "Read together, does `new` add nothing at all to `stored`: no new entity, value, "
            "qualifier, date or source that `stored` does not already carry?",
            criteria={
                "true": {
                    "what": "A restatement, a shorter form, or the same fact with different "
                    "wording",
                    "examples": ["'the fine was 500,000 pesos' and 'condemned to pay RD$500,000'"],
                },
                "false": {
                    "what": "It corrects a value, narrows it, dates it, sources it, or adds "
                    "any detail",
                    "examples": [
                        "'the fine was 500,000 pesos' against 'the fine was 500,000 pesos, "
                        "reduced on appeal to 200,000'"
                    ],
                },
            },
        ),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Reconciliation:
    action: Collision
    reason: str
    contradicts: float
    adds_nothing: float


def decide_collision(
    decision: Decision, t: Thresholds, *, newer: bool | None = None
) -> Reconciliation:
    """What the harness should do with a candidate memory that touches a stored one.

    `newer` is the harness's own answer to "is the new fact more recent than the stored
    one?", from timestamps it already holds. It is never asked of the decider: this model
    class reads dates as text and its own card says so. Without it, a real collision is
    flagged rather than resolved, because replacing the wrong way round is a silent loss.
    """
    if decision.failed:
        return Reconciliation("keep_both", "decider unavailable: both kept", 0.0, 0.0)
    against, nothing = decision.answer("contradicts"), decision.answer("adds_nothing")
    ps, pn = probability(against), probability(nothing)
    if against.empty or nothing.empty:
        return Reconciliation("keep_both", "no data: both kept", ps, pn)
    if pn >= t.act:
        return Reconciliation("duplicate", f"adds nothing ({pn:.2f})", ps, pn)
    if ps < t.act:
        return Reconciliation("keep_both", f"no contradiction ({ps:.2f})", ps, pn)
    if newer is True:
        return Reconciliation("replace", f"contradicts ({ps:.2f}), the new one is newer", ps, pn)
    if newer is False:
        return Reconciliation(
            "keep_both", f"contradicts ({ps:.2f}), the stored one is newer", ps, pn
        )
    return Reconciliation("flag", f"contradicts ({ps:.2f}), recency unknown", ps, pn)


# --- M3: does this turn need a lookup at all? -------------------------------------------


def recall_questions(
    *, turn: str, topics: str = ""
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    """One reading, gated hard: the default is to look."""
    state: dict[str, Any] = {"turn": truncate(turn, TURN_LIMIT)}
    if topics:
        state["topics"] = truncate(topics, TOPICS_LIMIT)
    qs: dict[str, Question] = {
        "needs_memory": Truth(
            "To answer `turn` well, does the agent need something it learned earlier and "
            "would not have in front of it now: a name, a value, a decision already taken, "
            "a preference already stated (`topics` lists what the store holds, if given)?",
            criteria={
                "true": {
                    "what": "It refers back, continues earlier work, or asks about an entity, "
                    "case or preference the store may already describe",
                    "examples": [
                        "carry on with the company we were looking at",
                        "what did we decide about the 2019 case?",
                        "write it up the way the client wants it",
                    ],
                },
                "false": {
                    "what": "Self-contained: everything it needs is in the turn itself, or it "
                    "is a generic operation on text that is already present",
                    "examples": [
                        "translate this paragraph into Spanish",
                        "what is 15 % of 4,200?",
                        "summarise the document I just pasted",
                    ],
                },
            },
        )
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Recall:
    look: bool
    reason: str
    probability: float


def decide_recall(decision: Decision, t: Thresholds) -> Recall:
    """Skip a lookup only on a confident no. Everything else looks, including a failure."""
    if decision.failed:
        return Recall(True, "decider unavailable: look", 0.0)
    answer = decision.answer("needs_memory")
    p = probability(answer, default=1.0)
    if answer.empty:
        return Recall(True, "no data: look", p)
    if p <= 1.0 - t.act:
        return Recall(False, f"self-contained ({p:.2f})", p)
    return Recall(True, f"may need what we know ({p:.2f})", p)
