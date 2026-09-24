"""The second annotator: another model, blind, over the bench cases.

    python benchmarks/annotate.py --benches loop-b.jsonl memory-b.jsonl \
        --out docs/results/2026-09-24-fifty --model claude-opus-5

Needs `ANTHROPIC_API_KEY`. Every call is metered and the bill is written next to the labels,
which is the whole reason this file exists rather than a script in somebody's scratchpad: the
first run of this annotator, on 2026-09-24, produced 212 labels and **no measured cost**,
because there was nothing to reach for and nobody noticed until afterwards.

What it is. Annotator 1 is the author, whose labels are the `expected` field of the bench
files. This is annotator 2: a generative model given the same question and the same criteria
the evaluator receives - rendered from the package's own question builders, so it answers the
literal question and not a paraphrase - and blind to both the author's label and the
evaluator's answer. It sees one case per request, so cases cannot contaminate each other.

What it is not. Two annotators, one of them a model, is not two independent humans. It cannot
see a criterion that is wrong in the same way for a model and for the author who wrote that
criterion in a model's idiom. `benchmarks/agreement.py` says the same where it reports kappa.

Re-running over an existing `annotator-2.jsonl` prints a stability report instead of silently
overwriting it: same cases, same prompts, a second sample. A label that moves between runs is
a label the bench should not be counting either way.

One measured note on cost, because it is the opposite of the intuition. Nothing here caches:
each case is its own request of a few hundred tokens, and the minimum cacheable prefix is 512
to 4096 tokens depending on the model, so there is no prefix long enough to cache. A
breakpoint on the system prompt was tried and read zero. That is the asymmetry the package is
about, seen from the other side: the expensive model earns its keep from a long shared
context, and a per-decision judgment has no long shared context to earn it from - which is
also why the same judgments cost 28.3 millionths each when a calibrated evaluator makes them
and about a hundred times that when a generative model does.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "benchmarks"))

import anthropic  # noqa: E402
from meter import Meter, Timed  # noqa: E402

from sanchopanza.points import graph, loop, memory, plan, triage  # noqa: E402

# Vocabulary and the rule by which the point's questions combine into one label, taken from
# the package's own `decide_*` functions. The questions themselves are never paraphrased.
POINTS: dict[str, tuple[list[str], str]] = {
    "goal_met": (
        ["true", "false"],
        "Answer true only if `done` already establishes everything `goal` asks for. If any "
        "part of the goal is unanswered, or `done` narrates attempts rather than results, "
        "answer false.",
    ),
    "repeats_check": (
        ["true", "false"],
        "Answer true only if the `pending` action would redo work that `done` already "
        "completed, with nothing changed since. Checking the same fact against a DIFFERENT "
        "source is corroboration, not a repeat. A check after a relevant change is not a "
        "repeat. A different part of the goal is not a repeat.",
    ),
    "memory_write": (
        ["store", "skip"],
        "Store only if the fact is durable AND specific AND not re-derivable from a source "
        "the agent already holds. If it is transient, vague, a restatement of the task, "
        "progress narration, general world knowledge, or re-readable from a document or "
        "repository already in hand, answer skip.",
    ),
    "recall": (
        ["look", "skip"],
        "Answer skip only if the turn is self-contained: it carries everything needed and "
        "depends on nothing agreed earlier. If it refers, even implicitly, to a prior "
        "decision, preference, format, exclusion or thread, answer look.",
    ),
    "extract_gate": (
        ["extract", "skip"],
        "Answer extract if the chunk names at least one instance of the kinds sought and "
        "says something about it, even in passing, even if the chunk is mostly something "
        "else. Answer skip only for structural or generic text with no instance at all.",
    ),
    "dependency": (
        ["true", "false"],
        "Answer true only if `line_b` consumes something `line_a` produces - a list, a "
        "dataset, a selection, a verdict - so that starting them together would make B wait "
        "or repeat work. Sharing a topic is not a dependency. Being merged later is not a "
        "dependency.",
    ),
    "redundant_page": (
        ["drop", "keep"],
        "Answer drop only if `text` carries no new figure, date, name, outcome, "
        "qualification or source that `known` lacks. Any new value, correction, "
        "qualification, or a different attribution when the purpose is corroboration, means "
        "keep. Judge only novelty against `known`; whether the page is on-topic is a "
        "different question that another point answers.",
    ),
}

SYSTEM_DIRECT = (
    "You are annotating a benchmark for a decision model. You are the second, independent "
    "annotator: you cannot see the first annotator's label and must not try to guess it. "
    "Read the state and the question's own criteria, apply them literally, and answer with "
    "exactly one word from the allowed set. No punctuation, no explanation, one word."
)

# The generative-verifier arm. Writing the justification before the verdict is the whole of
# what a GenRM does that a frozen scalar head cannot, and it is the control that item 12 of
# the paper's future work asks for on the compositional points.
SYSTEM_REASONING = (
    "You are annotating a benchmark for a decision model. You are the second, independent "
    "annotator: you cannot see the first annotator's label and must not try to guess it. "
    "Read the state and the question's own criteria and apply them literally. First write at "
    "most two short sentences working out the answer. Then, on a final line containing "
    "nothing else, write exactly one word from the allowed set."
)


def render_question(question: object) -> str:
    parts = [f"QUESTION: {question.instructions}"]  # type: ignore[attr-defined]
    criteria = getattr(question, "criteria", None)
    if criteria:
        parts.append("CRITERIA: " + json.dumps(criteria, ensure_ascii=False, indent=1))
    return "\n".join(parts)


def rubric(point: str, inp: dict) -> tuple[str, str]:
    """The state and the literal question(s), built by the package, not rewritten here."""
    if point in ("goal_met", "repeats_check"):
        state, qs = loop.questions(
            goal=inp["goal"],
            done=inp["done"],
            pending=inp.get("pending", ""),
            checks=inp.get("checks", ()),
        )
        one = qs[point]
    elif point == "memory_write":
        state, qs = memory.write_questions(fact=inp["fact"], brief="", source=inp.get("source", ""))
        one = None  # three questions combine into the label; show all of them
    elif point == "recall":
        state, qs = memory.recall_questions(turn=inp["turn"], topics=inp.get("topics", ""))
        one = qs["needs_memory"]
    elif point == "extract_gate":
        state, qs = graph.gate_questions(
            chunk=inp["chunk"], looking_for=inp["looking_for"], kinds=inp.get("kinds", ())
        )
        one = qs["has_anything"]
    elif point == "dependency":
        state, qs = plan.dependency_questions(
            a_title=inp["a_title"],
            a_goal=inp["a_goal"],
            b_title=inp["b_title"],
            b_goal=inp["b_goal"],
        )
        one = qs["b_needs_a"]
    elif point == "redundant_page":
        state, qs = triage.redundancy_questions(
            purpose=inp["purpose"], text=inp["text"], known=inp["known"]
        )
        one = qs["adds_nothing"]
    else:
        raise ValueError(f"unknown point: {point}")
    questions = (
        render_question(one)
        if one is not None
        else "\n\n".join(f"[{k}] {render_question(v)}" for k, v in qs.items())
    )
    return json.dumps(state, ensure_ascii=False, indent=1), questions


async def annotate(
    client,
    meter: Meter,
    sem,
    case: dict,
    model: str,
    *,
    reasoning: bool = False,
    effort: str | None = None,
    attempts: int = 6,
) -> dict:
    point = case["point"]
    vocabulary, rule = POINTS[point]
    state, questions = rubric(point, case["input"])
    # The closing line has to carry the format too: with only the system prompt asking for a
    # justification, the model reads the closing "answer with one word" as the instruction
    # that counts and answers in one word. Measured: 3 output tokens per call, no reasoning.
    closing = (
        "Work the answer out in at most two short sentences, naming what line A produces and "
        "what line B consumes where that is what the question turns on. Then write a final "
        f"line containing nothing but one of: {', '.join(vocabulary)}"
        if reasoning
        else f"Answer with exactly one of: {', '.join(vocabulary)}"
    )
    prompt = f"{questions}\n\nDECISION RULE: {rule}\n\nSTATE:\n{state}\n\n{closing}"
    text = ""
    async with sem:
        for attempt in range(attempts):
            try:
                with Timed() as t:
                    response = await client.messages.create(
                        model=model,
                        max_tokens=2000,
                        # No `cache_control`: this system prompt is about 60 tokens and the
                        # minimum cacheable prefix is 512 to 4096 depending on the model, so
                        # a breakpoint here caches nothing and only reads as if it did. The
                        # meter reports `cache_read` either way, and it is zero on this run.
                        system=SYSTEM_REASONING if reasoning else SYSTEM_DIRECT,
                        output_config={"effort": effort or ("medium" if reasoning else "low")},
                        messages=[{"role": "user", "content": prompt}],
                    )
            except (
                anthropic.RateLimitError,
                anthropic.APIStatusError,
                anthropic.APIConnectionError,
            ):
                await asyncio.sleep(5 * (attempt + 1))
                continue
            meter.add(response, label=point, seconds=t.seconds)
            text = "".join(b.text for b in response.content if b.type == "text").strip().lower()
            word = re.sub(r"[^a-z_]", "", text.split()[-1]) if text.split() else ""
            if word in vocabulary:
                return {
                    "id": case["id"],
                    "point": point,
                    "label": word,
                    "raw": text[:400] if reasoning else text[:80],
                }
    return {"id": case["id"], "point": point, "label": None, "raw": text[:80]}


def load_cases(benches: pathlib.Path, names: list[str]) -> list[dict]:
    cases = []
    for name in names:
        for line in (benches / name).read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                cases.append(json.loads(s))
    return cases


def stability(previous: dict[str, str | None], rows: list[dict]) -> str:
    """Same cases, same prompts, a second sample. A label that moves should not be counted."""
    shared = [r for r in rows if r["id"] in previous and previous[r["id"]] and r["label"]]
    if not shared:
        return ""
    moved = [r for r in shared if r["label"] != previous[r["id"]]]
    lines = [
        "",
        "## Stability against the previous run",
        "",
        f"{len(shared)} cases labelled in both runs; {len(shared) - len(moved)} identical "
        f"({(len(shared) - len(moved)) / len(shared):.1%}).",
    ]
    if moved:
        lines += ["", "| Case | Point | Previous | Now |", "|---|---|---|---|"]
        lines += [
            f"| {r['id']} | {r['point']} | {previous[r['id']]} | {r['label']} |" for r in moved
        ]
        lines.append("")
        lines.append(
            "A label that moves between two samples of the same prompt is a label the bench "
            "should not be counting in either direction. Treat each of these as disputed."
        )
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    benches = pathlib.Path(args.benches_dir)
    wanted = set(args.points) if args.points else set(POINTS)
    cases = [
        c
        for c in load_cases(benches, args.benches)
        if c["point"] in POINTS and c["point"] in wanted
    ]
    if args.limit:
        cases = cases[: args.limit]
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / args.name

    previous: dict[str, str | None] = {}
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                previous[row["id"]] = row["label"]

    print(f"{len(cases)} cases, {args.model}, concurrency {args.concurrency}", flush=True)
    meter = Meter(args.model, ledger=out / "annotator-usage.jsonl")
    client = anthropic.AsyncAnthropic()
    sem = asyncio.Semaphore(args.concurrency)
    started = time.perf_counter()
    rows = await asyncio.gather(
        *(
            annotate(
                client,
                meter,
                sem,
                c,
                args.model,
                reasoning=args.reasoning,
                effort=args.effort,
            )
            for c in cases
        )
    )
    wall = time.perf_counter() - started

    unlabelled = [r["id"] for r in rows if r["label"] is None]
    report = stability(previous, rows)

    destination = target if not previous or args.overwrite else out / f"{target.stem}-rerun.jsonl"
    destination.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    meter.write(out / "annotator-usage.json")

    print()
    print(meter.summary())
    print(f"wall clock: {wall:.1f} s")
    if unlabelled:
        print(f"cases with no label after retries: {len(unlabelled)} {unlabelled}")
    print(f"labels written to {destination}")
    if report:
        print(report)
        (out / "annotator-stability.md").write_text(report.lstrip("\n"), encoding="utf-8")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benches", nargs="+", required=True, help="bench file names")
    p.add_argument("--benches-dir", default="benches")
    p.add_argument("--out", required=True, help="results directory")
    p.add_argument("--name", default="annotator-2.jsonl")
    p.add_argument("--model", default="claude-opus-5")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument(
        "--points",
        nargs="*",
        default=None,
        help="only these points; default is every point this file knows",
    )
    p.add_argument(
        "--effort",
        default=None,
        choices=("low", "medium", "high", "xhigh", "max"),
        help="output_config.effort; default low, or medium with --reasoning",
    )
    p.add_argument(
        "--reasoning",
        action="store_true",
        help="generative-verifier arm: justify in at most two sentences, then answer",
    )
    p.add_argument("--limit", type=int, default=0, help="first N cases only, for a smoke test")
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="replace an existing label file instead of writing a -rerun one beside it",
    )
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
