"""The public benches replayed from the recorded fixture reproduce the paper's headline numbers.

No network: every decision comes from `fixtures/public-benches.jsonl`, a recording of the
real run of 2026-09-21. If the benches are not present (they are copied in separately), the
test is skipped rather than failed.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from sanchopanza.eval.bench import load_cases, run_bench, summarize
from sanchopanza.providers import RecordedDecider

ROOT = Path(__file__).resolve().parents[1]
BENCHES = Path(os.environ.get("SANCHO_BENCHES_DIR", ROOT / "benches"))
FIXTURE = ROOT / "fixtures" / "public-benches.jsonl"
FILES = ["core.jsonl", "safety.jsonl", "graph.jsonl"]


@pytest.fixture(scope="module")
def summary():
    if not FIXTURE.exists() or not all((BENCHES / f).exists() for f in FILES):
        pytest.skip("public benches or fixture not present")
    cases = load_cases(BENCHES / f for f in FILES)
    decider = RecordedDecider.from_file(FIXTURE)
    results = asyncio.run(run_bench(cases, decider))
    return summarize(results)


def test_every_case_was_answered_from_the_recording(summary):
    assert summary["cases"] == 245
    assert all(
        e["median_latency_ms"] > 0 or point == "command" for point, e in summary["points"].items()
    )


def test_headline_agreement_reproduces(summary):
    points = summary["points"]
    assert points["injection"]["hits"] == 28 and points["injection"]["auc"] == 1.0
    assert points["entity"]["hits"] == 24
    assert points["citation"]["hits"] == 18 and points["citation"]["decided"] == 18
    assert points["numeric_citation"]["hits"] == 22
    assert points["search"]["hits"] == 17
    assert points["triage"]["hits"] == 14
    assert points["unsourced"]["hits"] == 21
    assert points["dependency"]["hits"] == 19
    assert points["routing"]["hits"] == 14
    assert points["command"]["code_denials"]["combined"] >= 31


def test_confidence_separates_right_from_wrong(summary):
    bands = summary["bands"]
    high = bands["0.75-0.90"]["hits"] + bands["0.90-1.00"]["hits"]
    high_n = bands["0.75-0.90"]["n"] + bands["0.90-1.00"]["n"]
    low = sum(b["hits"] for k, b in bands.items() if k.startswith(("0.00", "0.40")))
    low_n = sum(b["n"] for k, b in bands.items() if k.startswith(("0.00", "0.40")))
    assert high / high_n > 0.95
    assert low / low_n < 0.6


def test_score_is_the_least_calibrated_primitive(summary):
    prims = summary["primitives"]
    assert prims["score"]["ece"] > prims["truth"]["ece"] > prims["choice"]["ece"]


def test_the_plan_dag_is_exact_after_code_cleanup(summary):
    plan = summary["plans"][0]
    assert plan["clean"]["precision"] == 1.0
    assert plan["clean"]["waves"] == plan["gold_waves"]
    assert plan["raw"]["precision"] < 0.5
