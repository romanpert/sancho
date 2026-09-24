"""Policies are pure: a table of decisions in, an action out. Asymmetry and defaults."""

from __future__ import annotations

import asyncio

from sanchopanza import Decision, Thresholds
from sanchopanza.points import citation, routing, search, triage
from sanchopanza.providers import FixedDecider

from .helpers import choice, decision, score, squire, thresholds, yes


def test_downgrading_needs_more_confidence_than_upgrading():
    t = thresholds(allow_upgrade=True)
    simple_doubtful = decision("routing", complexity=score(0.2, 0.65), person_risk=yes(0.0))
    simple_sure = decision("routing", complexity=score(0.2, 0.80), person_risk=yes(0.0))
    complex_ = decision("routing", complexity=score(1.8, 0.65), person_risk=yes(0.0))
    assert routing.decide(simple_doubtful, t).tier == "default"
    assert routing.decide(simple_sure, t).tier == "light"
    assert routing.decide(complex_, t).tier == "deep"


def test_never_upgrade_unless_allowed():
    complex_ = decision("routing", complexity=score(1.9, 0.95), person_risk=yes(0.0))
    assert routing.decide(complex_, thresholds(allow_upgrade=False)).tier == "default"


def test_a_task_about_a_person_never_goes_light():
    simple = decision("routing", complexity=score(0.1, 0.95), person_risk=yes(0.9))
    result = routing.decide(simple, thresholds())
    assert result.tier == "default" and "person" in result.reason and result.person_risk


def test_no_data_or_failure_keeps_the_default_everywhere():
    t = thresholds()
    assert routing.decide(decision("routing"), t).tier == "default"
    failed = Decision("x", {}, "jev", "-", error="HTTP 529")
    assert routing.decide(failed, t).tier == "default"
    route = search.decide(failed, t, cheap_available=True)
    assert route.route == "full"
    assert triage.decide(failed, t).keep is True
    assert citation.decide(failed, t, quote_found=True)[0] == "review"


def test_search_goes_cheap_only_with_a_cheap_engine_and_keyword_query():
    d = decision(
        "search", redundant=yes(0.1), source_kind=choice("news", 0.8), keyword_query=yes(0.9)
    )
    with_cheap = search.decide(d, thresholds(), cheap_available=True)
    without = search.decide(d, thresholds(), cheap_available=False)
    assert with_cheap.route == "cheap" and with_cheap.category == "news"
    assert without.route == "full"


def test_a_repeated_query_is_cut_by_model_or_by_code():
    by_model = decision("search", redundant=yes(0.95), keyword_query=yes(0.9))
    assert search.decide(by_model, thresholds(), cheap_available=True).route == "cut"
    failed = Decision("search", {}, "jev", "-", error="down")
    assert (
        search.decide(failed, thresholds(), cheap_available=True, repeat_by_code=True).route
        == "cut"
    )


def test_triage_drops_injection_and_irrelevance_but_keeps_doubt():
    t = thresholds()
    injected = decision("triage", injection=yes(0.9), relevant=yes(0.9))
    foreign = decision("triage", injection=yes(0.0), relevant=yes(0.2))
    good = decision("triage", injection=yes(0.0), relevant=yes(0.8), evidence=yes(0.7))
    assert triage.decide(injected, t).keep is False
    assert triage.decide(foreign, t).keep is False
    assert triage.decide(good, t).keep is True
    assert triage.decide(decision("triage"), t).keep is True


def test_citation_below_threshold_goes_to_review_and_absent_quote_is_fabricated():
    sure = decision("citation", relation=choice("contradicts", 0.95))
    doubtful = decision("citation", relation=choice("supports", 0.55))
    assert citation.decide(sure, thresholds(), quote_found=True) == ("contradicted", 0.95)
    assert citation.decide(doubtful, thresholds(), quote_found=True)[0] == "review"
    assert citation.decide(doubtful, thresholds(), quote_found=False) == ("fabricated", 1.0)


def test_thresholds_from_a_flat_mapping_ignores_unknown_keys():
    t = Thresholds.from_mapping(
        {"act": "0.8", "allow_upgrade": "yes", "max_decisions": "50", "x": 1}
    )
    assert t.act == 0.8 and t.allow_upgrade is True and t.max_decisions == 50
    assert t.relax == Thresholds().relax


# --- the pre-registered audit sample -------------------------------------------------------
#
# A threshold can only move on evidence, and evidence means re-labelled decisions. The way
# that goes wrong everywhere is that the cases get chosen after someone has seen which ones
# were right. So the sample is fixed by a hash of the decision's own answers: deterministic,
# reproducible, and decided before the outcome is known.


def _answered(point: str = "triage", p: float = 0.9):
    return decision(point, relevant=yes(p), evidence=yes(0.5))


def _flags(journal):
    return [e["data"].get("audit", False) for e in journal.events]


def test_no_sampling_by_default():
    sq, journal = squire(FixedDecider({}))
    sq.record(_answered())
    assert _flags(journal) == [False]


def test_the_sample_is_reproducible_on_a_replay():
    """Deterministic, not random: the same sequence yields the same sample, every time.

    The hash covers the decision's position as well as its answers. Hashing the answers
    alone looked simpler and was wrong: 200 identical decisions all landed on the same side
    of a 0.2 cut, because two decisions that answered the same way were the same draw. A
    confident binary point returns the same numbers all day, so that bias is not a corner
    case.
    """

    def one_session():
        sq, journal = squire(
            FixedDecider({"relevant": yes(0.9), "evidence": yes(0.8), "injection": yes(0.01)}),
            audit=0.3,
        )
        for i in range(40):
            asyncio.run(sq.triage_page(purpose=f"p{i}", text=f"texto {i}"))
        return _flags(journal)

    first, second = one_session(), one_session()
    assert first == second
    assert 0 < sum(first) < len(first)  # and it is a sample, not everything or nothing


def test_everything_is_sampled_at_one_and_nothing_at_zero():
    high, journal_high = squire(FixedDecider({}), audit=1.0)
    low, journal_low = squire(FixedDecider({}), audit=0.0)
    for i in range(6):
        high.record(_answered(p=0.5 + i / 20))
        low.record(_answered(p=0.5 + i / 20))
    assert all(_flags(journal_high))
    assert not any(_flags(journal_low))


def test_a_failed_or_empty_decision_is_never_sampled():
    sq, journal = squire(FixedDecider({}), audit=1.0)
    sq.record(Decision("triage", {}, "jev", "-", error="down"))
    sq.record(Decision("triage", {}, "jev", "-"))
    assert not any(_flags(journal))


def test_the_sample_is_roughly_the_fraction_asked_for():
    sq, journal = squire(FixedDecider({}), audit=0.2)
    for i in range(400):
        sq.record(decision("triage", relevant=yes(i / 400), evidence=yes(0.5)))
    taken = sum(_flags(journal))
    assert 40 <= taken <= 120  # 20 % of 400, loose: it is a hash, not a shuffle
