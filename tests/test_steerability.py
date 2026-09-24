"""Steerability: can the criterion be changed at query time, and where does that fail?

The bench behind these tests exists because of a marketing claim we could not check by
reading: that a cross-encoder reranker "cannot be steered" while a decision model can. The
design that makes it checkable is a flipped pair - same document, same topic, only the
criterion changes, and the correct answer flips with it - scored by **pair accuracy**.

The bound that gives the metric its teeth is arithmetic, not experimental: a scorer whose
inputs are only (query, document) cannot move when both are held fixed, so it answers both
sides of a pair the same way and scores 0 % pair accuracy. That bound covers a plain
cross-encoder and embedding similarity. It does **not** cover an instruction-following
reranker, which takes the criterion as input.

No test here calls a paid provider: the bench replays from `fixtures/steerability.jsonl`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sanchopanza import Answer, Decision
from sanchopanza.eval.bench import load_cases, run_bench
from sanchopanza.points import triage
from sanchopanza.providers import RecordedDecider

from .helpers import decision, thresholds, yes

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benches" / "steerability.jsonl"
FIXTURE = ROOT / "fixtures" / "steerability.jsonl"
T = thresholds()


def _choice(value: str, confidence: float) -> Answer:
    return Answer(kind="choice", choice=value, confidence=confidence)


# --- the measured failure, and the fix that resolves it -----------------------------------


def _the_case_that_failed() -> Decision:
    """st-01b, with the answers Jev actually returned (fixtures/steerability.jsonl).

    Criterion: "official primary sources ... not press that cites them". Document: a
    newspaper article carrying the figures. The relevance question answered 0.98, because
    the article *is* about the topic, and the page was kept. The provenance answer was in
    the same decision: `news` at confidence 1.00.
    """
    return decision(
        "triage",
        relevant=yes(0.98),
        evidence=yes(0.97),
        injection=yes(0.01),
        source_kind=_choice("news", 1.0),
    )


def test_a_provenance_criterion_in_the_purpose_alone_does_not_work():
    """The failure, pinned. Relevance is not the question a provenance rule is asking."""
    assert triage.decide(_the_case_that_failed(), T).keep


def test_the_same_decision_resolves_it_once_code_reads_the_source_kind():
    result = triage.decide(_the_case_that_failed(), T, allowed_kinds={"official_records"})
    assert not result.keep
    assert "news" in result.reason and result.source_kind == "news"


def test_a_denied_kind_is_dropped_too():
    result = triage.decide(_the_case_that_failed(), T, denied_kinds={"news", "social"})
    assert not result.keep


def test_an_allowed_kind_still_goes_through_the_relevance_rule():
    official = decision(
        "triage",
        relevant=yes(0.02),
        evidence=yes(0.10),
        injection=yes(0.01),
        source_kind=_choice("official_records", 0.99),
    )
    result = triage.decide(official, T, allowed_kinds={"official_records"})
    assert not result.keep and "not relevant" in result.reason


def test_an_unsure_source_kind_keeps_the_page():
    """Doubt keeps, here as everywhere: a provenance filter must not become a silent cull."""
    unsure = decision(
        "triage",
        relevant=yes(0.90),
        evidence=yes(0.80),
        injection=yes(0.01),
        source_kind=_choice("news", 0.40),
    )
    assert triage.decide(unsure, T, allowed_kinds={"official_records"}).keep


def test_no_source_kind_data_keeps_the_page():
    blind = decision("triage", relevant=yes(0.90), evidence=yes(0.80), injection=yes(0.01))
    assert triage.decide(blind, T, allowed_kinds={"official_records"}).keep


def test_the_filter_is_off_unless_asked_for():
    assert triage.decide(_the_case_that_failed(), T).keep


# --- the bench itself, replayed ------------------------------------------------------------


@pytest.fixture(scope="module")
def pairs():
    if not FIXTURE.exists() or not BENCH.exists():
        pytest.skip("steerability bench or fixture not present")
    cases = load_cases([BENCH])
    pair_of = {c["id"]: c["pair"] for c in cases}
    rows = asyncio.run(run_bench(cases, RecordedDecider.from_file(FIXTURE)))
    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(pair_of[r.id], []).append(r)
    return grouped


def test_the_answer_moves_when_only_the_criterion_moves(pairs):
    """The capability under test. A (query, document) scorer scores 0 here by construction."""
    changed = [p for p, rs in pairs.items() if rs[0].predicted != rs[1].predicted]
    assert len(changed) == 11
    assert len(pairs) == 14


def test_pair_accuracy_reproduces(pairs):
    both_right = [p for p, rs in pairs.items() if all(r.correct for r in rs)]
    assert len(both_right) == 11  # 11/14 pairs, 25/28 cases


def test_the_three_failures_are_the_ones_we_documented(pairs):
    """Provenance, language of the document, and a date comparison.

    st-14 was declared a negative control before the run, because its criterion turns on a
    date and this model class reads dates as text. Its twin st-13, also date-based, passed:
    the weakness is real and it is not absolute.
    """
    failed = sorted(p for p, rs in pairs.items() if not all(r.correct for r in rs))
    assert failed == ["st-01", "st-09", "st-14"]


def test_the_bench_is_made_of_complete_flipped_pairs():
    """Structural: every pair has two sides with opposite labels, or the metric is a lie."""
    cases = json.loads(json.dumps([c for c in load_cases([BENCH])]))  # load_cases strips comments
    by_pair: dict[str, list] = {}
    for c in cases:
        by_pair.setdefault(c["pair"], []).append(c["expected"])
    assert all(sorted(v) == ["drop", "keep"] for v in by_pair.values())
