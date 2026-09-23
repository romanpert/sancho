"""`sancho` command line.

sanchopanza bench benches/*.jsonl --provider recorded --fixture fixtures/public-benches.jsonl
sanchopanza bench benches/*.jsonl --provider jev --record fixtures/new.jsonl --out results/today
sanchopanza hook            # Claude Code hook: JSON in, JSON out
sanchopanza providers       # what is installed
sanchopanza dag plan.json   # clean DAG and waves from {"nodes": [...], "edges": {"A->B": 0.9}}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .dag import build_dag, waves
from .eval.bench import load_cases, render_markdown, rows_to_json, run_bench, summarize
from .providers import available, create
from .providers.recorded import RecordingDecider


def _bench(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    if args.provider == "recorded":
        decider = create("recorded", path=args.fixture)
    elif args.provider == "jev":
        decider = create("jev", api_key=os.environ.get("TYPESAFE_API_KEY"))
    else:
        decider = create(args.provider)
    if args.record:
        decider = RecordingDecider(decider, args.record)
    results = asyncio.run(run_bench(cases, decider, concurrency=args.concurrency))
    summary = summarize(results)
    text = render_markdown(summary, title=args.title)
    sys.stdout.write(text)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(
            json.dumps(rows_to_json(results), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        (out / "summary.md").write_text(text, encoding="utf-8")
        (out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    return 0


def _hook(_args: argparse.Namespace) -> int:
    from .harness.claude_code import main as hook_main

    return hook_main()


def _providers(_args: argparse.Namespace) -> int:
    for name, target in sorted(available().items()):
        sys.stdout.write(f"{name:10} {target}\n")
    return 0


def _dag(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    nodes = list(data["nodes"])
    edges = {tuple(k.split("->")): float(v) for k, v in data["edges"].items()}
    clean = build_dag(nodes, edges, threshold=args.threshold)  # type: ignore[arg-type]
    sys.stdout.write(
        json.dumps({"edges": sorted(clean), "waves": waves(nodes, clean)}, indent=1) + "\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sancho", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    bench = sub.add_parser("bench", help="run labelled cases through the squire")
    bench.add_argument("cases", nargs="+", help="JSONL bench files")
    bench.add_argument(
        "--provider", default="recorded", help="recorded | jev | null | <entry point>"
    )
    bench.add_argument("--fixture", default="fixtures/public-benches.jsonl")
    bench.add_argument("--record", default=None, help="append real decisions to this fixture file")
    bench.add_argument("--out", default=None, help="directory for results.json and summary.md")
    bench.add_argument("--title", default="Bench results")
    bench.add_argument("--concurrency", type=int, default=4)
    bench.set_defaults(func=_bench)

    hook = sub.add_parser("hook", help="Claude Code hook (stdin JSON -> stdout JSON)")
    hook.set_defaults(func=_hook)

    providers = sub.add_parser("providers", help="list installed providers")
    providers.set_defaults(func=_providers)

    dag = sub.add_parser("dag", help="clean DAG and waves from probabilistic pairs")
    dag.add_argument("plan")
    dag.add_argument("--threshold", type=float, default=0.5)
    dag.set_defaults(func=_dag)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
