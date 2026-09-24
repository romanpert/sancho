"""The fifty-cases-per-point bench, replayed from its recording.

No network: every decision comes from `fixtures/new-points-50.jsonl`, a recording of the run
of 2026-09-24. These tests pin what that run established, so that a change to a question, a
threshold or a label has to be deliberate and shows up as a failing test:

1. the agreement per point on the harder cases;
2. **the gap between what the model orders correctly and what the shipped thresholds act
   on**, which reopened on these cases after the 0.2.0 fix had closed it on the easy ones;
3. that every error the policy makes is still a refusal to act;
4. the sample-size floor, which is the run's actual result: fifty cases per point support a
   precision target of 80 % and nothing above it.

If the benches or the fixture are absent the module is skipped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sanchopanza.eval.bench import load_cases, run_bench, summarize
from sanchopanza.providers import RecordedDecider

ROOT = Path(__file__).resolve().parents[1]
BENCHES = ROOT / "benches"
FIXTURE = ROOT / "fixtures" / "new-points-50.jsonl"
FILES = ["loop-b.jsonl", "memory-b.jsonl", "graph-build-b.jsonl", "retrieval-b.jsonl"]
BINARY = ("extract_gate", "goal_met", "memory_write", "recall", "redundant_page", "repeats_check")


@pytest.fixture(scope="module")
def run():
    if not FIXTURE.exists() or not all((BENCHES / f).exists() for f in FILES):
        pytest.skip("fifty-case benches or fixture not present")
    cases = load_cases(BENCHES / f for f in FILES)
    results = asyncio.run(run_bench(cases, RecordedDecider.from_file(FIXTURE)))
    return summarize(results), results


def test_the_recording_covers_the_whole_bench(run):
    summary, _ = run
    assert summary["cases"] == 212
    assert summary["calls"] == 212
    assert summary["cost_usd"] / summary["calls"] < 3e-5  # 28.3 millionths of a dollar


def test_every_binary_point_reaches_fifty_with_the_first_batch(run):
    """The point of this file: 34 to 38 new cases on top of the 12 to 20 already published."""
    counts = {p: run[0]["points"][p]["n"] for p in BINARY}
    assert counts == {
        "extract_gate": 34,
        "goal_met": 36,
        "memory_write": 34,
        "recall": 36,
        "redundant_page": 34,
        "repeats_check": 38,
    }


def test_agreement_per_point_reproduces(run):
    points = run[0]["points"]
    assert points["extract_gate"]["hits"] == 30
    assert points["goal_met"]["hits"] == 35
    assert points["memory_write"]["hits"] == 26
    assert points["recall"]["hits"] == 36
    assert points["redundant_page"]["hits"] == 26
    assert points["repeats_check"]["hits"] == 37
    assert sum(points[p]["hits"] for p in BINARY) == 190


def test_the_gap_against_a_plain_cut_reopened_on_the_hard_cases(run):
    """190 under the policy, 202 at 0.5, and all of it in two points.

    On the first 124 cases the 0.2.0 fix closed this gap to three decisions. It is back at
    twelve here, and it is no longer the hidden-gate defect: it is two single thresholds,
    0.70 and 0.80, declining to act. A tuning pass has to beat this number.
    """
    _, results = run
    binary = [r for r in results if r.point in BINARY and r.probability is not None]
    at_half = sum(1 for r in binary if _predicted_at_half(r) == r.expected)
    assert at_half == 202
    assert at_half - 190 == 12


def test_every_policy_error_is_a_refusal_to_act(run):
    """memory_write only fails by not storing; redundant_page only by not dropping."""
    _, results = run
    for point, action in (("memory_write", "store"), ("redundant_page", "drop")):
        wrong = [r for r in results if r.point == point and r.correct is False]
        assert wrong, "the point is supposed to have errors on these cases"
        assert all(r.expected == action and r.predicted != action for r in wrong)


def test_fifty_cases_support_an_eighty_percent_target_and_no_more():
    """Pure arithmetic, and the run's real finding. See `benchmarks/thresholds.py`."""
    import math

    z = 1.96

    def lower(k: int, n: int) -> float:
        centre = (k + z * z / 2) / (n + z * z)
        half = z / (n + z * z) * math.sqrt(k * (n - k) / n + z * z / 4)
        return max(0.0, centre - half)

    needed = {t: next(n for n in range(1, 1000) if lower(n, n) >= t) for t in (0.80, 0.90, 0.95)}
    assert needed == {0.80: 16, 0.90: 35, 0.95: 73}
    # A point with 50 labelled cases at a balanced mix acts on about 25 of them.
    assert lower(25, 25) >= 0.80
    assert lower(25, 25) < 0.90


def _predicted_at_half(row) -> object:
    """The label a plain 0.5 cut would give, in the row's own vocabulary."""
    high = {
        "memory_write": ("store", "skip"),
        "redundant_page": ("drop", "keep"),
        "goal_met": (True, False),
        "repeats_check": (True, False),
    }
    low = {"extract_gate": ("skip", "extract"), "recall": ("skip", "look")}
    if row.point in high:
        yes, no = high[row.point]
        return yes if row.probability >= 0.5 else no
    yes, no = low[row.point]
    return yes if row.probability <= 0.5 else no
