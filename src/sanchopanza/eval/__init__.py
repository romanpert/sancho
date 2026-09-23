"""Measure before you trust: benches, statistics, calibration by primitive.

    sanchopanza bench benches/*.jsonl --provider recorded --fixture fixtures/public-benches.jsonl

A bench is a JSON-lines file of labelled cases: {"id", "point", "input", "expected"}. The
runner sends each case through the same `Squire` methods production uses, so what is
measured is the policy as deployed, not the model alone.
"""

from .bench import Row, load_cases, run_bench, summarize

__all__ = ["Row", "load_cases", "run_bench", "summarize"]
