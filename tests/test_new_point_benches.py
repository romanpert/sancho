"""The new points' bench replayed from its recording, including the finding that hurts.

No network: every decision comes from `fixtures/new-points.jsonl`, a recording of the run
of 2026-09-24. The tests below pin three things on purpose:

1. the headline agreement per point, so a change to a question or a policy has to be
   deliberate and show up as a failing test;
2. **the gap between what the model orders correctly and what the shipped thresholds act
   on**, which is the real finding of that run and the thing a future tuning pass has to
   beat;
3. that every error the policy makes is a refusal to act rather than a wrong action.

If the benches or the fixture are absent the module is skipped, as the public one is.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sanchopanza.eval.bench import load_cases, run_bench, summarize
from sanchopanza.providers import RecordedDecider

ROOT = Path(__file__).resolve().parents[1]
BENCHES = ROOT / "benches"
FIXTURE = ROOT / "fixtures" / "new-points.jsonl"
FILES = ["memory.jsonl", "graph-build.jsonl", "retrieval.jsonl", "loop.jsonl"]
BINARY = ("extract_gate", "goal_met", "memory_write", "recall", "redundant_page", "repeats_check")


@pytest.fixture(scope="module")
def run():
    if not FIXTURE.exists() or not all((BENCHES / f).exists() for f in FILES):
        pytest.skip("new-point benches or fixture not present")
    cases = load_cases(BENCHES / f for f in FILES)
    results = asyncio.run(run_bench(cases, RecordedDecider.from_file(FIXTURE)))
    return summarize(results), results


def test_the_recording_covers_the_whole_bench(run):
    summary, _ = run
    assert summary["cases"] == 124
    assert summary["calls"] == 122  # two edge cases are settled in code, before any call
    assert summary["cost_usd"] / summary["calls"] < 3e-5  # 29 millionths of a dollar


def test_agreement_per_point_reproduces(run):
    points = run[0]["points"]
    assert points["goal_met"]["hits"] == 14 and points["goal_met"]["decided"] == 14
    assert points["repeats_check"]["hits"] == 12
    assert points["recall"]["hits"] == 14
    assert points["extract_gate"]["hits"] == 15
    assert points["memory_write"]["hits"] == 12
    assert points["memory_collision"]["hits"] == 14
    assert points["redundant_page"]["hits"] == 11
    assert points["edge"]["hits"] == 15 and points["edge"]["decided"] == 17


def test_the_ordering_is_perfect_on_every_binary_point(run):
    """AUC 1.00 everywhere: no error on these points is an ordering error."""
    points = run[0]["points"]
    assert all(points[p]["auc"] == 1.0 for p in BINARY)


def test_the_shipped_thresholds_cost_more_than_the_model_does(run):
    """The finding of the first run, pinned so a tuning pass has to improve on it.

    At a plain 0.5 cut the six binary points get 86 of 88. Under the thresholds the package
    ships, the same decisions come out at 78 of 88. The eight lost decisions are the price
    of thresholds inherited from the points measured in the paper, on a Truth primitive that
    is under-confident. They are not tuned here: the rule is 50 cases and a second annotator
    per point before a threshold moves, and this bench has 12 to 20 and one annotator.
    """
    points = run[0]["points"]
    at_half = sum(points[p]["at_0.5"] for p in BINARY)
    under_policy = sum(points[p]["hits"] for p in BINARY)
    assert at_half == 86
    assert under_policy == 78
    assert under_policy < at_half


def test_every_policy_error_is_a_refusal_to_act(run):
    """The asymmetries hold: the layer declines to act, it never acts wrongly."""
    _, results = run
    safe = {
        "memory_write": "skip",
        "redundant_page": "keep",
        "extract_gate": "extract",
        "memory_collision": "keep_both",
    }
    for row in results:
        point = getattr(row, "point", None)
        if point in safe and row.correct is False:
            assert row.predicted == safe[point], (row.id, row.predicted)


def test_no_wrong_edge_is_ever_committed(run):
    """The only edge metric that matters: a wrong edge poisons everything downstream."""
    _, results = run
    edges = [r for r in results if getattr(r, "point", None) == "edge"]
    committed = [r for r in edges if r.predicted == "supported"]
    assert len(committed) == 8
    assert all(r.expected == "supported" for r in committed)


def test_confidence_separates_right_from_wrong_here_too(run):
    """The paper's central result, replicated on points it was not derived from."""
    bands = run[0]["bands"]
    high = sum(b["hits"] for k, b in bands.items() if k.startswith(("0.75", "0.90")))
    high_n = sum(b["n"] for k, b in bands.items() if k.startswith(("0.75", "0.90")))
    low = sum(b["hits"] for k, b in bands.items() if not k.startswith(("0.75", "0.90")))
    low_n = sum(b["n"] for k, b in bands.items() if not k.startswith(("0.75", "0.90")))
    assert high / high_n > 0.95  # 92/94
    assert low / low_n < 0.6  # 15/27
