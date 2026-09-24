"""Does writing the reasoning first help, and only where the judgment is compositional?

    python benchmarks/genrm.py --results docs/results/2026-09-24-genrm \
        --compositional dependency --control recall

Free: it reads label files already on disk. Nothing is called.

The claim being tested is not ours and it is the strongest piece of counter-evidence against
this package's architecture. A generative verifier that writes a justification before its
verdict beats a frozen scalar head on multi-step judgments; if that holds here, then the
defensible line is not "non-generative wins", it is **"closed-vocabulary judgments go to a
typed head and compositional ones do not"**, and the package should route by question shape
rather than by price.

The design is a two-by-two, because a one-armed result would prove nothing. Each point is
answered by the same frontier model twice - once answering in a single word, once working the
answer out in two sentences first - and the two points are chosen to differ in exactly the
property under test:

  - **compositional** (`dependency`): does line B consume what line A produces? The answer
    requires holding two goals side by side and tracing an artefact from one to the other.
  - **control** (`recall`): is this turn self-contained? A single judgment about one string.

If reasoning helps on the compositional point and not on the control, the hypothesis
survives. If it helps on both, the finding is about the model and not about composition. If
it helps on neither, the counter-evidence does not reproduce here, which is worth publishing
precisely because we went looking for it.

Expected label files in `--results`, one directory per arm:
`<point>-direct/annotator-2.jsonl` and `<point>-reasoning/annotator-2.jsonl`, plus each
arm's `annotator-usage.json` for what it cost.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


def norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def read_labels(path: pathlib.Path) -> dict[str, str | None]:
    labels: dict[str, str | None] = {}
    if not path.exists():
        return labels
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            labels[row["id"]] = row["label"]
    return labels


def read_usage(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def expected_labels(benches: pathlib.Path, point: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(benches.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                row = json.loads(s)
                if row["point"] == point:
                    out[row["id"]] = norm(row["expected"])
    return out


def evaluator_hits(results: pathlib.Path, point: str) -> tuple[int, int] | None:
    """The evaluator's score on the same point, from a bench results.json if one is here."""
    for candidate in (results / "evaluator" / "results.json", results / "results.json"):
        if candidate.exists():
            rows = [
                r for r in json.loads(candidate.read_text(encoding="utf-8")) if r["point"] == point
            ]
            if rows:
                return sum(1 for r in rows if r["correct"]), len(rows)
    return None


def arm(results: pathlib.Path, benches: pathlib.Path, point: str, mode: str) -> dict | None:
    directory = results / f"{point}-{mode}"
    labels = read_labels(directory / "annotator-2.jsonl")
    if not labels:
        return None
    truth = expected_labels(benches, point)
    shared = [i for i in labels if labels[i] and i in truth]
    hits = sum(1 for i in shared if labels[i] == truth[i])
    usage = read_usage(directory / "annotator-usage.json")
    calls = usage.get("usage", {}).get("calls", 0) or len(shared)
    cost = usage.get("cost_usd", 0.0)
    out_tokens = usage.get("usage", {}).get("output", 0)
    return {
        "mode": mode,
        "n": len(shared),
        "hits": hits,
        "cost": cost,
        "per_call": cost / calls if calls else 0.0,
        "output_tokens": out_tokens,
        "labels": labels,
        "truth": truth,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", required=True)
    p.add_argument("--benches", default="benches")
    p.add_argument("--compositional", default="dependency")
    p.add_argument("--control", default="recall")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    results = pathlib.Path(args.results)
    benches = pathlib.Path(args.benches)

    lines = [
        "# A generative verifier as a control on a compositional judgment",
        "",
        "The same frontier model answers each point twice: once in a single word, once after "
        "working the answer out in two sentences. The compositional point and the control "
        "differ in whether the judgment requires tracing an artefact between two objects.",
        "",
        "| Point | Shape | Arm | n | Correct | Cost per judgment | Output tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    summary: dict[str, Any] = {}
    for point, shape in ((args.compositional, "compositional"), (args.control, "control")):
        evaluator = evaluator_hits(results, point)
        if evaluator:
            lines.append(
                f"| {point} | {shape} | evaluator | {evaluator[1]} | "
                f"{evaluator[0]}/{evaluator[1]} | 28 millionths | 0 |"
            )
        for mode in ("direct", "reasoning"):
            a = arm(results, benches, point, mode)
            if not a:
                continue
            summary.setdefault(point, {})[mode] = {
                k: v for k, v in a.items() if k not in ("labels", "truth")
            }
            lines.append(
                f"| {point} | {shape} | {mode} | {a['n']} | {a['hits']}/{a['n']} | "
                f"{a['per_call'] * 1e6:.0f} millionths | {a['output_tokens']:,} |"
            )

    lines += ["", "## What moved", ""]
    for point, shape in ((args.compositional, "compositional"), (args.control, "control")):
        d = summary.get(point, {}).get("direct")
        r = summary.get(point, {}).get("reasoning")
        if not d or not r:
            continue
        delta = r["hits"] - d["hits"]
        cost_ratio = r["per_call"] / d["per_call"] if d["per_call"] else float("nan")
        word = "gained" if delta > 0 else ("lost" if delta < 0 else "changed")
        lines.append(
            f"- **{point}** ({shape}): reasoning {word} {abs(delta)} "
            f"decision{'s' if abs(delta) != 1 else ''} out of {d['n']}, at "
            f"{cost_ratio:.1f}x the cost per judgment."
        )
        da = arm(results, benches, point, "direct")
        ra = arm(results, benches, point, "reasoning")
        if da and ra:
            moved = [
                i
                for i in da["labels"]
                if ra["labels"].get(i) and da["labels"][i] != ra["labels"][i]
            ]
            if moved:
                lines.append(
                    f"  Cases whose label changed between the two arms: {', '.join(sorted(moved))}"
                )
    text = "\n".join(lines)
    print(text)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
