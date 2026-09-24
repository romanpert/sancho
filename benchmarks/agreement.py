"""Agreement between the two annotators and the evaluator.

    python benchmarks/agreement.py --results docs/results/2026-09-24-fifty --benches benches

Free: it reads files and counts. Nothing is called.

Annotator 1 is the author, whose labels are the `expected` field of the bench files.
Annotator 2 is a separate generative model, whose labels are `annotator-2.jsonl` in the
results directory, produced blind to both the first label and the evaluator's answer.

Two annotators, one of them a model, is **not** the two independent humans the literature
assumes when it reports an inter-annotator agreement, and the number below should never be
quoted as though it were. It cannot see a criterion that is wrong in the same way for the
model and for the author who wrote that criterion in the model's idiom. What it can see, and
what it is for, is a case whose label depends on the annotator rather than on the criteria.

The last two lines are the ones worth reading: the evaluator's agreement where the two
annotators agree, against its agreement where they do not. A point whose errors cluster on
the cases humans would argue about is a point with an ambiguous question, not a bad model.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

POINTS = (
    "extract_gate",
    "goal_met",
    "memory_write",
    "recall",
    "redundant_page",
    "repeats_check",
)
FILES = ("loop-b.jsonl", "memory-b.jsonl", "graph-build-b.jsonl", "retrieval-b.jsonl")


def norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def kappa(pairs: list[tuple[str, str]]) -> tuple[float, float]:
    """Raw agreement and Cohen's kappa."""
    n = len(pairs)
    labels = sorted({x for pair in pairs for x in pair})
    observed = sum(1 for a, b in pairs if a == b) / n
    expected = sum(
        (sum(1 for a, _ in pairs if a == label) / n) * (sum(1 for _, b in pairs if b == label) / n)
        for label in labels
    )
    return observed, ((observed - expected) / (1 - expected) if expected < 1 else 1.0)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", required=True)
    p.add_argument("--benches", default="benches")
    args = p.parse_args()

    results_dir = pathlib.Path(args.results)
    benches = pathlib.Path(args.benches)

    second: dict[str, str | None] = {}
    for line in (results_dir / "annotator-2.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            second[row["id"]] = row["label"]

    first: dict[str, Any] = {}
    for name in FILES:
        path = benches / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                row = json.loads(s)
                first[row["id"]] = row["expected"]

    rows = json.loads((results_dir / "results.json").read_text(encoding="utf-8"))
    evaluator = {r["id"]: r["predicted"] for r in rows}
    point_of = {r["id"]: r["point"] for r in rows}

    missing = [i for i, v in second.items() if v is None]
    if missing:
        print(f"Cases the second annotator did not label: {len(missing)} {missing}\n")

    print("| Point | n | A1 vs A2 | Cohen's kappa | A1 vs evaluator | A2 vs evaluator |")
    print("|---|---|---|---|---|---|")
    everything: list[tuple[str, str]] = []
    for point in POINTS:
        ids = [i for i in point_of if point_of[i] == point and second.get(i)]
        if not ids:
            continue
        pairs = [(norm(first[i]), norm(second[i])) for i in ids]
        observed, k = kappa(pairs)
        everything += pairs
        a1 = sum(1 for i in ids if norm(first[i]) == norm(evaluator[i])) / len(ids)
        a2 = sum(1 for i in ids if norm(second[i]) == norm(evaluator[i])) / len(ids)
        print(f"| {point} | {len(ids)} | {observed:.0%} | {k:.2f} | {a1:.0%} | {a2:.0%} |")

    ids = [i for i in point_of if second.get(i)]
    observed, k = kappa(everything)
    a1 = sum(1 for i in ids if norm(first[i]) == norm(evaluator[i])) / len(ids)
    a2 = sum(1 for i in ids if norm(second[i]) == norm(evaluator[i])) / len(ids)
    print(
        f"| **all** | {len(everything)} | **{observed:.0%}** | **{k:.2f}** | "
        f"**{a1:.0%}** | **{a2:.0%}** |"
    )

    disputed = sorted(i for i in ids if norm(first[i]) != norm(second[i]))
    print("\n## Cases the two annotators labelled differently\n")
    print("| Case | Point | Annotator 1 | Annotator 2 | Evaluator |")
    print("|---|---|---|---|---|")
    for i in disputed:
        print(
            f"| {i} | {point_of[i]} | {norm(first[i])} | {norm(second[i])} | {norm(evaluator[i])} |"
        )

    agreed = [i for i in ids if norm(first[i]) == norm(second[i])]
    hits = sum(1 for i in agreed if norm(evaluator[i]) == norm(first[i]))
    print(
        f"\nWhere both annotators agree ({len(agreed)} cases) the evaluator agrees with them "
        f"{hits} times, {hits / len(agreed):.0%}."
    )
    if disputed:
        with_first = sum(1 for i in disputed if norm(evaluator[i]) == norm(first[i]))
        print(
            f"Where they disagree ({len(disputed)} cases) the evaluator sides with annotator 1 "
            f"{with_first} times and with annotator 2 {len(disputed) - with_first} times."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
