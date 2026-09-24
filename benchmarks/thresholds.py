"""Derive a threshold to a target precision, the way a deployed system does it.

    python benchmarks/thresholds.py --derive docs/results/A --eval docs/results/B

Free: it reads two bench result files and does arithmetic. Nothing is called.

Why this exists. `docs/paper.md` Section 8 promised "fifty cases and a second annotator per
new point, then thresholds set the way Google sets them: per point, to a target precision,
reported as recall@X" [Frommgen et al., 2024]. This is that, plus the part the promise left
out: **whether the sample is large enough for the target to mean anything.**

Two rules make the difference between deriving a threshold and fitting one to its own score:

1. **Derive on one set, report on another.** The threshold is chosen using only `--derive`
   and every number reported comes from `--eval`. A threshold picked and scored on the same
   cases will always look good and predicts nothing.
2. **Require the LOWER BOUND of precision to meet the target, not the point estimate.** With
   a dozen acted cases, an observed precision of 100 % has a 95 % Wilson lower bound near
   68 %. Choosing "the least strict threshold whose observed precision reaches the target"
   therefore picks an extreme that does not survive contact with new data - we tried it, and
   it produced thresholds of 0.13 and 0.23 that missed their own target out of sample by up
   to 16 points. Requiring the lower bound is what turns "target precision" into a claim that
   can fail.

The consequence is a sample-size floor that is pure arithmetic, and it is the useful output
of this file. With perfect observed precision, the number of ACTED cases needed for the 95 %
Wilson lower bound to clear a target is:

| Target | Acted cases needed | Labelled cases per point, at a balanced label mix |
|---|---|---|
| 80 % | 16 | about 32 |
| 90 % | 35 | about 70 |
| 95 % | 73 | about 146 |

So fifty cases per point supports an 80 % precision target and nothing above it. Raising a
threshold to a 90 % target is not a labelling afternoon; it is 70 cases per point.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
from typing import Any

# point -> (label emitted when the squire ACTS, direction in which acting happens).
# "high": act when p >= threshold. "low": act when p <= threshold.
ACTION: dict[str, tuple[Any, str]] = {
    "memory_write": ("store", "high"),
    "redundant_page": ("drop", "high"),
    "goal_met": (True, "high"),
    "repeats_check": (True, "high"),
    "extract_gate": ("skip", "low"),
    "recall": ("skip", "low"),
}
# The threshold in force today, expressed in the same orientation as the curve.
SHIPPED = {
    "memory_write": 0.70,
    "redundant_page": 0.80,
    "goal_met": 0.50,
    "repeats_check": 0.50,
    "extract_gate": 0.25,
    "recall": 0.25,
}
Z = 1.96


def wilson_lower(k: int, n: int) -> float:
    """95 % Wilson lower bound on k/n. The whole method turns on using this, not k/n."""
    if n == 0:
        return 0.0
    centre = (k + Z * Z / 2) / (n + Z * Z)
    half = Z / (n + Z * Z) * math.sqrt(k * (n - k) / n + Z * Z / 4)
    return max(0.0, centre - half)


def load(directory: pathlib.Path) -> list[dict]:
    rows = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    return [r for r in rows if r["point"] in ACTION and r.get("probability") is not None]


def acted(rows: list[dict], threshold: float, direction: str) -> list[dict]:
    if direction == "high":
        return [r for r in rows if r["probability"] >= threshold]
    return [r for r in rows if r["probability"] <= threshold]


def score(rows: list[dict], threshold: float, point: str) -> tuple[float, float, int]:
    """Precision and recall of the acted direction, plus total agreement at that threshold."""
    label, direction = ACTION[point]
    act = acted(rows, threshold, direction)
    positives = sum(1 for r in rows if r["expected"] == label)
    hits = sum(1 for r in act if r["expected"] == label)
    precision = hits / len(act) if act else float("nan")
    recall = hits / positives if positives else float("nan")
    keep = set(id(r) for r in act)
    total = sum(1 for r in rows if (r["expected"] == label) == (id(r) in keep))
    return precision, recall, total


def derive(rows: list[dict], point: str, target: float) -> float | None:
    """The threshold with the most recall whose precision LOWER BOUND clears the target."""
    label, direction = ACTION[point]
    positives = sum(1 for r in rows if r["expected"] == label)
    best: tuple[float, float] | None = None
    for step in range(1, 100):
        threshold = step / 100
        act = acted(rows, threshold, direction)
        if not act:
            continue
        hits = sum(1 for r in act if r["expected"] == label)
        if wilson_lower(hits, len(act)) < target:
            continue
        recall = hits / positives if positives else 0.0
        if best is None or recall > best[1]:
            best = (threshold, recall)
    return None if best is None else best[0]


def floor_table() -> str:
    lines = [
        "| Target precision | Acted cases needed | Labelled cases per point (balanced) |",
        "|---|---|---|",
    ]
    for target in (0.80, 0.90, 0.95):
        n = next(n for n in range(1, 1000) if wilson_lower(n, n) >= target)
        lines.append(f"| {target:.0%} | {n} | about {2 * n} |")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--derive", required=True, help="results dir the threshold is chosen on")
    p.add_argument("--eval", required=True, help="results dir every reported number comes from")
    p.add_argument("--targets", default="0.80,0.90,0.95")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    derivation = load(pathlib.Path(args.derive))
    evaluation = load(pathlib.Path(args.eval))
    targets = [float(x) for x in args.targets.split(",")]

    print("## Sample-size floor (arithmetic, no data)\n")
    print(floor_table())
    print(
        "\nA target above what the sample supports is not conservatism, it is an unfalsifiable"
        "\nclaim: the lower bound can never reach it however good the model is.\n"
    )
    print("## Derived thresholds\n")
    print(
        "| Point | Acts by | Shipped | Target | Derived | Precision (held out) | Recall | "
        "Agreement at derived | Agreement at shipped |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    summary: dict[str, Any] = {}
    for point in ACTION:
        sd = [r for r in derivation if r["point"] == point]
        se = [r for r in evaluation if r["point"] == point]
        if not sd or not se:
            continue
        _, _, shipped_hits = score(se, SHIPPED[point], point)
        for target in targets:
            threshold = derive(sd, point, target)
            if threshold is None:
                print(
                    f"| {point} | {ACTION[point][0]} | {SHIPPED[point]:.2f} | {target:.0%} | "
                    f"unreachable at n={len(sd)} | - | - | - | {shipped_hits}/{len(se)} |"
                )
                summary.setdefault(point, {})[f"{target:.2f}"] = {"reachable": False, "n": len(sd)}
                continue
            precision, recall, hits = score(se, threshold, point)
            flag = "" if precision >= target else " **misses it**"
            print(
                f"| {point} | {ACTION[point][0]} | {SHIPPED[point]:.2f} | {target:.0%} | "
                f"{threshold:.2f} | {precision:.0%}{flag} | {recall:.0%} | "
                f"{hits}/{len(se)} | {shipped_hits}/{len(se)} |"
            )
            summary.setdefault(point, {})[f"{target:.2f}"] = {
                "reachable": True,
                "threshold": threshold,
                "precision_held_out": precision,
                "recall_held_out": recall,
                "agreement": hits,
                "agreement_shipped": shipped_hits,
                "n_eval": len(se),
                "n_derive": len(sd),
            }
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
