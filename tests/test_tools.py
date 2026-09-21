"""Tool selection is fail-open, never empty, pins `always`, drops only the clearly unneeded."""

from __future__ import annotations

from sancho import Decision
from sancho.points import tools

from .helpers import decision, thresholds, yes

CATALOG = [
    {
        "name": "aemps",
        "about": "Spanish medicines agency: SmPC, leaflets, shortages",
        "tags": ["regulatory", "es"],
    },
    {"name": "boe", "about": "Spanish official gazette: laws and decrees", "tags": ["legal", "es"]},
    {"name": "chembl", "about": "Bioactivity and medicinal chemistry", "tags": ["chemistry"]},
    {"name": "websearch", "about": "General web search", "tags": ["search"]},
]
NAMES = tuple(g["name"] for g in CATALOG)


def test_questions_are_one_truth_per_group_with_positional_ids():
    state, qs = tools.questions(purpose="interacción Sintrom con ibuprofeno", catalog=CATALOG)
    assert list(qs) == ["needed_0", "needed_1", "needed_2", "needed_3"]
    assert state["catalog"][0]["name"] == "aemps" and "clues" not in state
    assert "`catalog[2]`" in qs["needed_2"].instructions and "chembl" in qs["needed_2"].instructions


def test_a_failed_decision_keeps_the_full_catalog():
    failed = Decision("tools", {}, "jev", "-", error="HTTP 529")
    sel = tools.decide(failed, thresholds(), catalog=CATALOG)
    assert sel.keep == NAMES and not sel.narrowed and "unavailable" in sel.reason


def test_no_data_keeps_the_full_catalog():
    sel = tools.decide(decision("tools"), thresholds(), catalog=CATALOG)
    assert sel.keep == NAMES and sel.reason.startswith("no data")


def test_groups_below_the_threshold_are_dropped_and_always_groups_are_pinned():
    d = decision(
        "tools", needed_0=yes(0.92), needed_1=yes(0.08), needed_2=yes(0.05), needed_3=yes(0.40)
    )
    sel = tools.decide(d, thresholds(), catalog=CATALOG, always=("websearch",))
    assert sel.keep == ("aemps", "websearch")
    assert sel.dropped == ("boe", "chembl")
    assert sel.probabilities["aemps"] == 0.92 and sel.narrowed


def test_a_pinned_group_stays_even_at_zero_probability():
    d = decision(
        "tools", needed_0=yes(0.9), needed_1=yes(0.0), needed_2=yes(0.0), needed_3=yes(0.0)
    )
    sel = tools.decide(d, thresholds(), catalog=CATALOG, always=("chembl",))
    assert "chembl" in sel.keep and "boe" in sel.dropped


def test_the_selection_is_never_empty_beyond_the_pinned_groups():
    d = decision(
        "tools", needed_0=yes(0.20), needed_1=yes(0.05), needed_2=yes(0.30), needed_3=yes(0.10)
    )
    sel = tools.decide(d, thresholds(), catalog=CATALOG, always=("websearch",))
    assert sel.keep == ("chembl", "websearch")  # best of the rest is kept, catalog order preserved
    assert "kept best" in sel.reason


def test_a_group_without_an_answer_is_kept():
    d = decision("tools", needed_0=yes(0.9), needed_1=yes(0.01))  # groups 2 and 3 unanswered
    sel = tools.decide(d, thresholds(), catalog=CATALOG)
    assert sel.keep == ("aemps", "chembl", "websearch") and sel.dropped == ("boe",)


def test_the_threshold_is_the_one_from_the_policy():
    d = decision(
        "tools", needed_0=yes(0.5), needed_1=yes(0.5), needed_2=yes(0.5), needed_3=yes(0.5)
    )
    assert tools.decide(d, thresholds(tools=0.6), catalog=CATALOG).keep == ("aemps",)  # best kept
    assert tools.decide(d, thresholds(tools=0.5), catalog=CATALOG).keep == NAMES
