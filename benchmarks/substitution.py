"""The same judgments, made two ways: what substitution actually buys.

    python benchmarks/substitution.py --results docs/results/2026-09-24-fifty

Free: it reads artefacts already on disk. Nothing is called.

This is the claim the package exists for, and the only one of the three economies in
`docs/where-it-pays.md` whose arithmetic is safe: a cheap calibrated decision pays when it
**replaces a call a bigger model was going to make anyway**. Everything else in this
repository - page triage, redundancy, context pruning - is avoidance, and avoidance measured
null twice.

The comparison here is unusually clean, and it fell out of doing something else. The second
annotator of `benchmarks/annotate.py` is a frontier generative model asked, one case per
request, **the same questions from the same question builders** that the evaluator is asked,
over the same bench cases. So the two artefacts in a results directory are two independent
answers to one set of judgments:

  - `results.json`       the evaluator's answer, its cost and its latency
  - `annotator-2.jsonl`  the generative model's answer
  - `annotator-usage.json` what that generative model cost and how long it took

Accuracy is measured the same way for both: agreement with the bench's `expected` labels,
which neither of them saw. That is the part that makes the price ratio mean something - a
cheaper answer that is worse is not a saving, it is a discount on a different product.

Two honest notes about what the ratio is not. The generative model here is run at `low`
effort with a one-word answer, so it is close to the cheapest a frontier model can be asked
to do this; and it caches nothing, because a per-decision prompt of a few hundred tokens is
below the minimum cacheable prefix. Both facts push the comparison *towards* the generative
model, not away from it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from meter import price_of  # noqa: E402

POINTS = (
    "extract_gate",
    "goal_met",
    "memory_write",
    "recall",
    "redundant_page",
    "repeats_check",
)


def norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def load(results: pathlib.Path) -> tuple[list[dict], dict[str, str | None], dict]:
    rows = json.loads((results / "results.json").read_text(encoding="utf-8"))
    labels: dict[str, str | None] = {}
    path = results / "annotator-2.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                labels[row["id"]] = row["label"]
    usage_path = results / "annotator-usage.json"
    usage = json.loads(usage_path.read_text(encoding="utf-8")) if usage_path.exists() else {}
    return rows, labels, usage


def ledger_latency(results: pathlib.Path) -> float | None:
    """Median seconds per call from the annotator's ledger, if it recorded them."""
    path = results / "annotator-usage.jsonl"
    if not path.exists():
        return None
    seconds = [
        json.loads(line)["seconds"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    seconds = [s for s in seconds if s]
    return statistics.median(seconds) if seconds else None


def _at_half(row: dict) -> str:
    """The label a plain 0.5 cut on the probability would give, in the row's vocabulary.

    Included because comparing a frontier model against the shipped thresholds conflates two
    different questions - how good is the model, and how good are the thresholds - and only
    the first one is about substitution.
    """
    high = {
        "memory_write": ("store", "skip"),
        "redundant_page": ("drop", "keep"),
        "goal_met": ("true", "false"),
        "repeats_check": ("true", "false"),
    }
    low = {"extract_gate": ("skip", "extract"), "recall": ("skip", "look")}
    p = row.get("probability")
    if p is None:
        return norm(row["predicted"])
    if row["point"] in high:
        yes, no = high[row["point"]]
        return yes if p >= 0.5 else no
    yes, no = low[row["point"]]
    return yes if p <= 0.5 else no


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", required=True)
    p.add_argument("--out", default=None, help="write the table to this markdown file")
    args = p.parse_args()

    results = pathlib.Path(args.results)
    rows, labels, usage = load(results)
    rows = [r for r in rows if r["point"] in POINTS]
    expected = {r["id"]: norm(r["expected"]) for r in rows}

    shared = [r for r in rows if labels.get(r["id"])]
    if not shared:
        print("no annotator labels in that directory; nothing to compare", file=sys.stderr)
        return 2

    ev_hits = sum(1 for r in shared if norm(r["predicted"]) == expected[r["id"]])
    cut_hits = sum(1 for r in shared if _at_half(r) == expected[r["id"]])
    gen_hits = sum(1 for r in shared if norm(labels[r["id"]]) == expected[r["id"]])
    n = len(shared)

    ev_cost = sum(r.get("cost_usd", 0.0) for r in rows)
    ev_calls = sum(1 for r in rows if r.get("cost_usd") is not None)
    ev_latency = statistics.median([r["latency_ms"] for r in shared if r.get("latency_ms")])

    gen_cost = usage.get("cost_usd", 0.0)
    gen_model = usage.get("model", "?")
    gen_calls = usage.get("usage", {}).get("calls", 0)
    gen_seconds = usage.get("usage", {}).get("seconds", 0.0)
    gen_latency_ms = (ledger_latency(results) or 0.0) * 1000

    per_ev = ev_cost / ev_calls if ev_calls else 0.0
    per_gen = gen_cost / gen_calls if gen_calls else 0.0
    ratio = per_gen / per_ev if per_ev else float("nan")
    speed = gen_latency_ms / ev_latency if ev_latency else float("nan")
    rate_in, rate_out = price_of(gen_model) if gen_model in {gen_model} else (0, 0)

    lines = [
        "# The same judgments, made two ways",
        "",
        f"{n} judgments from `{results.name}`, each answered independently by a calibrated "
        "non-generative evaluator and by a frontier generative model given the same question, "
        "the same criteria and the same state. Neither saw the bench labels.",
        "",
        "| | Evaluator, shipped policy | Evaluator, plain 0.5 cut | Generative model |",
        "|---|---|---|---|",
        f"| Model | `{rows[0].get('model', 'jev')}` | same | `{gen_model}` |",
        f"| Judgments | {ev_calls} | {ev_calls} | {gen_calls} |",
        f"| Agreement with the bench labels | {ev_hits}/{n} = {ev_hits / n:.0%} | "
        f"{cut_hits}/{n} = {cut_hits / n:.0%} | {gen_hits}/{n} = {gen_hits / n:.0%} |",
        f"| Total cost | {ev_cost:.4f} USD | same | {gen_cost:.4f} USD |",
        f"| Cost per judgment | {per_ev * 1e6:.1f} millionths | same | "
        f"{per_gen * 1e6:.0f} millionths |",
        f"| Median latency | {ev_latency:.0f} ms | same | {gen_latency_ms:.0f} ms |",
        f"| Wall clock, all judgments | - | - | {gen_seconds:.0f} s of model time |",
        "",
        f"**{ratio:.0f}x cheaper per judgment, {speed:.1f}x faster, and "
        f"{gen_hits - cut_hits} decision{'s' if abs(gen_hits - cut_hits) != 1 else ''} less "
        f"accurate** than the frontier model at a plain cut - "
        f"{gen_hits - ev_hits} under the thresholds actually shipped.",
        "",
        "## What this is",
        "",
        "Substitution, measured end to end on a real set of judgments rather than argued from "
        "a price list, and it is not a tie. The frontier model is the more accurate judge: "
        f"{gen_hits}/{n} against {ev_hits}/{n} under the shipped policy. But most of that gap "
        "is the thresholds and not the model - at a plain 0.5 cut the evaluator reaches "
        f"{cut_hits}/{n}, and the remaining difference is "
        f"{gen_hits - cut_hits} decision{'s' if abs(gen_hits - cut_hits) != 1 else ''}.",
        "",
        "So the trade is stated honestly like this: **the cheap evaluator gives up a small "
        f"amount of accuracy and buys back {ratio:.0f}x the price and {speed:.1f}x the "
        "latency.** Whether that trade is worth taking is a property of the decision, not of "
        "the models: it is obviously worth it for a gate in front of a generative pass, and "
        "obviously not for a judgment that is the deliverable. The size of the gap is also the "
        "size of the prize for deriving better thresholds, which is why "
        "`benchmarks/thresholds.py` exists.",
        "",
        "## What it is not",
        "",
        "- It is not a claim that the evaluator is as good as the generative model at anything "
        "else. These are closed-vocabulary judgments over a supplied state, which is the shape "
        "the package claims and the only shape it claims.",
        "- The generative model is run at `low` effort answering in one word, which is close to "
        "the cheapest a frontier model can be asked to do this. The ratio would be larger at "
        "any realistic effort setting, not smaller.",
        "- Neither side caches: a per-decision prompt is below the minimum cacheable prefix. A "
        "judgment made inside a long warm conversation would be read at the cached rate, which "
        "is the correction `docs/where-it-pays.md` applies to *avoidance* and which does not "
        "apply here, because these calls are separate requests either way.",
        f"- Prices are list prices ({rate_in:.2f} in / {rate_out:.2f} out USD per MTok for "
        f"`{gen_model}`), so this is arithmetic over reported tokens and not a bill.",
    ]
    text = "\n".join(lines)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
