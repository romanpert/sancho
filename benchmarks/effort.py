"""What buying more thinking actually buys, on judgments a typed head also answers.

    python benchmarks/effort.py --results docs/results/2026-09-24-effort \
        --arms low medium high xhigh --benches benches

Free: it reads label files and meter ledgers already on disk. Nothing is called.

Why. The substitution measurement in `benchmarks/substitution.py` ran the generative arm at
`low` effort answering in one word, which is close to the cheapest a frontier model can be
asked to make these judgments. That is the conservative choice for a price ratio - it makes
the expensive side as cheap as possible - but it leaves the obvious question unanswered:
**does the frontier model get meaningfully better at these judgments if you pay it to
think?** If it does, the honest ratio is bigger than the one we published and the quality gap
is smaller. If it does not, then on this shape of judgment thinking buys nothing, which is a
stronger claim than the price ratio on its own.

Each arm is the same cases, the same prompt and the same model, differing only in
`output_config.effort`. Accuracy is agreement with the bench labels, which no arm saw.
Latency is the median of the per-call seconds in each arm's meter ledger, so it is a
per-judgment figure and not a wall clock confounded by concurrency.

Layout expected in `--results`: one directory per arm, named after the effort level, each
holding `annotator-2.jsonl` and `annotator-usage.json` from `benchmarks/annotate.py`.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from typing import Any


def norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def expected_labels(benches: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(benches.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                row = json.loads(s)
                out[row["id"]] = norm(row["expected"])
    return out


def read_arm(directory: pathlib.Path) -> dict | None:
    labels_path = directory / "annotator-2.jsonl"
    if not labels_path.exists():
        return None
    labels = {}
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            labels[row["id"]] = row["label"]
    usage_path = directory / "annotator-usage.json"
    usage = json.loads(usage_path.read_text(encoding="utf-8")) if usage_path.exists() else {}
    ledger = directory / "annotator-usage.jsonl"
    seconds = []
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line).get("seconds")
                if value:
                    seconds.append(value)
    return {"labels": labels, "usage": usage, "seconds": seconds}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", required=True)
    p.add_argument("--arms", nargs="+", required=True)
    p.add_argument("--benches", default="benches")
    p.add_argument("--baseline", default=None, help="an arm to express ratios against")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    results = pathlib.Path(args.results)
    truth = expected_labels(pathlib.Path(args.benches))

    arms: dict[str, dict] = {}
    for name in args.arms:
        arm = read_arm(results / name)
        if arm:
            arms[name] = arm
    if not arms:
        print(f"no arms found under {results}", file=sys.stderr)
        return 2

    # Only cases every arm labelled, so the columns compare like with like.
    common = set.intersection(
        *[{i for i, v in a["labels"].items() if v and i in truth} for a in arms.values()]
    )
    base = args.baseline or args.arms[0]

    lines = [
        "# What more thinking buys on a closed-vocabulary judgment",
        "",
        f"{len(common)} cases answered by every arm. Same model, same prompt, same cases; the "
        "only difference is `output_config.effort`. Accuracy is agreement with the bench "
        "labels, which no arm saw.",
        "",
        "| Effort | Correct | Output tokens | Cost | Per judgment | Median latency |",
        "|---|---|---|---|---|---|",
    ]
    rows: dict[str, dict] = {}
    for name, arm in arms.items():
        hits = sum(1 for i in common if arm["labels"][i] == truth[i])
        usage = arm["usage"].get("usage", {})
        calls = usage.get("calls", 0) or len(arm["labels"])
        cost = arm["usage"].get("cost_usd", 0.0)
        per = cost / calls if calls else 0.0
        latency = statistics.median(arm["seconds"]) * 1000 if arm["seconds"] else 0.0
        rows[name] = {
            "hits": hits,
            "cost": cost,
            "per": per,
            "latency": latency,
            "output": usage.get("output", 0),
        }
        lines.append(
            f"| {name} | {hits}/{len(common)} = {hits / len(common):.0%} | "
            f"{usage.get('output', 0):,} | {cost:.4f} USD | {per * 1e6:.0f} millionths | "
            f"{latency:.0f} ms |"
        )

    if base in rows:
        b = rows[base]
        lines += ["", f"## Against `{base}`", ""]
        for name, r in rows.items():
            if name == base:
                continue
            d = r["hits"] - b["hits"]
            word = "gains" if d > 0 else ("loses" if d < 0 else "changes")
            lines.append(
                f"- **{name}**: {word} {abs(d)} decision{'s' if abs(d) != 1 else ''}, "
                f"costs {r['per'] / b['per']:.2f}x per judgment, "
                f"{r['latency'] / b['latency']:.1f}x the latency"
                if b["per"] and b["latency"]
                else f"- **{name}**: {word} {abs(d)} decisions"
            )
        moved = sorted(i for i in common if len({arms[n]["labels"][i] for n in arms}) > 1)
        if moved:
            lines += [
                "",
                f"Cases where the arms do not all agree ({len(moved)}): " + ", ".join(moved),
                "",
                "A case whose label depends on how hard the model was asked to think is a "
                "case whose label depends on a setting, not on the criteria. Those are the "
                "ones to read before believing any of the columns above.",
            ]

    text = "\n".join(lines)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
