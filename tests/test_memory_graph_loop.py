"""The points added for memory, graph construction, redundancy and the loop guard.

Every test here is about an *asymmetry*, because that is what a decision layer gets wrong
silently. An accuracy bug shows up in a bench; a threshold pointing the wrong way shows up
as a memory that quietly lost a fact, a graph that quietly gained a wrong edge, or an agent
that quietly stopped early. So each point is tested at four places: the confident yes, the
confident no, the doubt, and the provider that is not there at all.

No test calls a paid provider.
"""

from __future__ import annotations

import asyncio

from sanchopanza import Decision
from sanchopanza.points import graph, loop, memory, triage
from sanchopanza.providers import FixedDecider
from sanchopanza.providers.fixed import BrokenDecider

from .helpers import decision, squire, thresholds, yes

T = thresholds()


# --- M1: writing to memory ---------------------------------------------------------------


def test_a_durable_specific_fact_is_stored():
    d = decision("memory_write", durable=yes(0.95), specific=yes(0.93), derivable=yes(0.05))
    assert memory.decide_write(d, T).store


def test_a_fact_that_can_be_re_read_from_the_source_is_not_stored():
    """The rule that keeps a store from becoming a slow copy of the repository."""
    d = decision("memory_write", durable=yes(0.95), specific=yes(0.95), derivable=yes(0.96))
    result = memory.decide_write(d, T)
    assert not result.store and "re-readable" in result.reason


def test_a_transient_fact_is_not_stored():
    d = decision("memory_write", durable=yes(0.08), specific=yes(0.90), derivable=yes(0.10))
    assert not memory.decide_write(d, T).store


def test_doubt_does_not_write():
    """Writing is the costly direction: a junk memory is read for the rest of the job."""
    d = decision("memory_write", durable=yes(0.55), specific=yes(0.80), derivable=yes(0.10))
    assert not memory.decide_write(d, T).store


def test_no_decider_does_not_write():
    assert not memory.decide_write(decision("memory_write"), T).store
    assert not memory.decide_write(Decision("memory_write", {}, "x", "-", error="down"), T).store


# --- M2: collisions with what is already stored -------------------------------------------


def test_a_restatement_is_a_duplicate():
    d = decision("memory_collision", contradicts=yes(0.05), adds_nothing=yes(0.96))
    assert memory.decide_collision(d, T).action == "duplicate"


def test_a_contradiction_with_a_known_newer_fact_replaces():
    d = decision("memory_collision", contradicts=yes(0.95), adds_nothing=yes(0.10))
    assert memory.decide_collision(d, T, newer=True).action == "replace"


def test_a_contradiction_with_unknown_recency_is_flagged_not_resolved():
    """Dates are the model class's declared weakness, so recency is never asked of it."""
    d = decision("memory_collision", contradicts=yes(0.95), adds_nothing=yes(0.10))
    assert memory.decide_collision(d, T, newer=None).action == "flag"


def test_the_stored_fact_being_newer_keeps_both():
    d = decision("memory_collision", contradicts=yes(0.95), adds_nothing=yes(0.10))
    assert memory.decide_collision(d, T, newer=False).action == "keep_both"


def test_corroboration_from_a_second_source_keeps_both():
    """Same field, same value, another source: the first draft of this point flagged it."""
    d = decision("memory_collision", contradicts=yes(0.06), adds_nothing=yes(0.35))
    assert memory.decide_collision(d, T).action == "keep_both"


def test_nothing_is_ever_deleted_without_a_decider():
    assert memory.decide_collision(decision("memory_collision"), T).action == "keep_both"


# --- M3: recall gating ---------------------------------------------------------------------


def test_a_self_contained_turn_skips_the_lookup():
    d = decision("recall", needs_memory=yes(0.03))
    assert not memory.decide_recall(d, T).look


def test_doubt_looks():
    """Skipping a needed lookup costs an answer; a needless one costs a few hundred tokens."""
    d = decision("recall", needs_memory=yes(0.30))
    assert memory.decide_recall(d, T).look


def test_no_decider_looks():
    assert memory.decide_recall(decision("recall"), T).look


# --- G5: the extraction gate ---------------------------------------------------------------


def test_boilerplate_is_not_sent_to_the_extractor():
    assert not graph.decide_gate(decision("extract_gate", has_anything=yes(0.02)), T).extract


def test_anything_that_might_carry_an_entity_is_extracted():
    assert graph.decide_gate(decision("extract_gate", has_anything=yes(0.35)), T).extract
    assert graph.decide_gate(decision("extract_gate"), T).extract


# --- G6: the edge check --------------------------------------------------------------------


def test_a_stated_triple_is_committed():
    d = decision("edge", stated=yes(0.96), direction=yes(0.95))
    assert graph.decide_edge(d, T).commit


def test_a_reversed_triple_is_caught_and_not_committed():
    d = decision("edge", stated=yes(0.93), direction=yes(0.04))
    result = graph.decide_edge(d, T)
    assert result.verdict == "reversed" and not result.commit


def test_an_unstated_triple_is_unsupported():
    d = decision("edge", stated=yes(0.03), direction=yes(0.50))
    assert graph.decide_edge(d, T).verdict == "unsupported"


def test_a_doubtful_triple_goes_to_review_rather_than_into_the_graph():
    """A wrong edge poisons everything downstream, so doubt never commits."""
    d = decision("edge", stated=yes(0.62), direction=yes(0.80))
    assert graph.decide_edge(d, T).verdict == "review"


def test_a_mention_absent_from_the_text_needs_no_model_call():
    result = graph.decide_edge(decision("edge"), T, mentions_found=False)
    assert result.verdict == "unsupported" and result.confidence == 1.0


def test_the_squire_short_circuits_an_invented_mention():
    sq, journal = squire(FixedDecider({"stated": yes(0.99), "direction": yes(0.99)}))
    result = asyncio.run(
        sq.verify_edge(subject="Omega Holdings", relation="owns", obj="Delta", text="nothing here")
    )
    assert result.verdict == "unsupported"
    assert journal.decisions()[0]["provider"] == "code"


# --- D3b: redundancy -----------------------------------------------------------------------


def test_a_page_that_repeats_what_is_known_is_dropped():
    d = decision("redundant_page", adds_nothing=yes(0.94))
    assert triage.decide_redundancy(d, T).drop


def test_a_page_that_might_add_something_is_kept():
    d = decision("redundant_page", adds_nothing=yes(0.72))
    assert not triage.decide_redundancy(d, T).drop


def test_redundancy_fails_open_into_keeping_the_page():
    assert not triage.decide_redundancy(decision("redundant_page"), T).drop
    sq, _ = squire(BrokenDecider())
    result = asyncio.run(sq.triage_redundant(purpose="p", text="t", known="k"))
    assert not result.drop


# --- the loop guard ------------------------------------------------------------------------


def test_it_says_the_goal_is_met_only_when_confident():
    d = decision("loop", goal_met=yes(0.95), repeats_check=yes(0.10))
    advice = loop.decide(d, T)
    assert advice.speaks and "established already" in advice.message


def test_it_names_a_repeated_check():
    d = decision("loop", goal_met=yes(0.20), repeats_check=yes(0.93))
    assert "already run" in loop.decide(d, T).message


def test_it_stays_quiet_in_doubt():
    """Stopping too early is the expensive error, and the operator is the one who sees it."""
    assert not loop.decide(decision("loop", goal_met=yes(0.65), repeats_check=yes(0.50)), T).speaks


def test_it_stays_quiet_without_a_decider():
    assert not loop.decide(decision("loop"), T).speaks
    sq, _ = squire(BrokenDecider())
    assert not asyncio.run(sq.check_loop(goal="g", done="d")).speaks


# --- every new point is traced -------------------------------------------------------------


def test_each_new_point_writes_one_journal_event():
    answers = {
        "durable": yes(0.9),
        "specific": yes(0.9),
        "derivable": yes(0.1),
        "contradicts": yes(0.9),
        "adds_nothing": yes(0.2),
        "needs_memory": yes(0.9),
        "has_anything": yes(0.9),
        "stated": yes(0.9),
        "direction": yes(0.9),
        "goal_met": yes(0.2),
        "repeats_check": yes(0.2),
    }
    sq, journal = squire(FixedDecider(answers))
    asyncio.run(sq.remember("fact"))
    asyncio.run(sq.reconcile(new="a", stored="b"))
    asyncio.run(sq.needs_recall("turn"))
    asyncio.run(sq.gate_extraction(chunk="c", looking_for="people"))
    asyncio.run(sq.verify_edge(subject="a", relation="r", obj="b", text="a r b"))
    asyncio.run(sq.check_loop(goal="g", done="d", pending="p"))
    asyncio.run(sq.triage_redundant(purpose="p", text="t", known="k"))
    points = [e["point"] for e in journal.decisions()]
    assert points == [
        "memory_write",
        "memory_collision",
        "recall",
        "extract_gate",
        "edge",
        "loop",
        "redundant_page",
    ]
