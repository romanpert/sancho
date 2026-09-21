"""Run labelled cases through the squire and report agreement, coverage, calibration.

Case format (one JSON object per line; lines starting with # are comments):

    {"id": "rt-01", "point": "routing", "input": {"task": "...", "brief": "..."},
     "expected": "light"}

Points and their inputs / labels:

    routing          task, brief                       light | default | deep
    search           query, previous, brief            cut | cheap | full
    triage           purpose, title, url, text         keep | drop
    citation         claim, section                    supported | contradicted | unsupported
    numeric_citation claim, section                    (same; numbers inside)
    injection        purpose, text                     true | false
    command          command                           true | false (dangerous)
    unsourced        task, result                      true | false
    entity           a, context_a, b, context_b        true | false (same entity)
    facts            fact_a, fact_b                    agree | conflict | unrelated
    dependency       a_title, a_goal, b_title, b_goal  true | false (b needs a)
    plan             lines [{id,title,goal}], edges    (evaluated as a whole: precision/recall)
    classify         field, text, options, context     one of the options

Each row records what the policy decided, with what confidence, and the raw probability
for binary points, so AUC, Brier and ECE can be recomputed from the JSON.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..contract import Decider, truth_confidence
from ..dag import build_dag, transitive_closure, transitive_reduction, waves
from ..journal import MemoryJournal
from ..policy import Thresholds
from ..squire import Squire
from . import stats

BANDS = ((0.0, 0.4), (0.4, 0.6), (0.6, 0.75), (0.75, 0.9), (0.9, 1.01))
BINARY_POINTS = frozenset({"injection", "command", "unsourced", "entity", "dependency"})
PRIMITIVE_OF = {
    "routing": "score",
    "search": "truth",
    "triage": "truth",
    "citation": "choice",
    "numeric_citation": "choice",
    "injection": "truth",
    "command": "truth",
    "unsourced": "truth",
    "entity": "truth",
    "facts": "choice",
    "dependency": "truth",
    "classify": "choice",
}


@dataclass(frozen=True, slots=True)
class Row:
    id: str
    point: str
    expected: Any
    predicted: Any
    correct: bool | None
    decided: bool
    confidence: float
    probability: float | None
    primitive: str
    provider: str
    model: str
    latency_ms: int
    input_tokens: int
    cost_usd: float


def load_cases(paths: Iterable[Path | str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                cases.append(json.loads(line))
    return cases


def _bench_thresholds(t: Thresholds) -> Thresholds:
    # The bench lets the routing point upgrade so that all three tiers are reachable.
    return t.with_(allow_upgrade=True)


async def _run_case(
    squire: Squire, journal: MemoryJournal, case: Mapping[str, Any]
) -> Row | dict[str, Any]:
    point, inp, expected = case["point"], case["input"], case.get("expected")
    before = len(journal.events)
    predicted: Any
    confidence: float
    probability: float | None = None

    if point == "routing":
        r = await squire.route_task(inp["task"])
        predicted, confidence = r.tier, r.confidence
    elif point == "search":
        squire._queries = tuple(inp.get("previous", []))  # noqa: SLF001 - bench sets history
        r = await squire.route_search(inp["query"], cheap_available=True)
        predicted = r.route
        confidence = max(
            truth_confidence(r.keyword_probability), truth_confidence(r.redundant_probability)
        )
        if r.route == "cut" and r.redundant_probability >= 1.0:
            confidence = 1.0
    elif point == "triage":
        r = await squire.triage_page(
            purpose=inp["purpose"],
            title=inp.get("title", ""),
            url=inp.get("url", ""),
            text=inp["text"],
        )
        predicted = "keep" if r.keep else "drop"
        confidence = truth_confidence(r.relevance) if r.reason != "decider unavailable" else 0.0
    elif point in ("citation", "numeric_citation"):
        # the bench assumes the quote is present: it measures meaning, not literal match
        verdict, confidence = await _citation(squire, inp["claim"], inp["section"])
        predicted = verdict
    elif point == "injection":
        from ..points import injection as inj

        state, qs = inj.questions(purpose=inp.get("purpose", ""), text=inp["text"])
        decision = await squire.decide("injection", state, qs)
        squire.record(decision)
        probability = decision.answer("injection").truth
        predicted = None if probability is None else probability >= 0.5
        confidence = truth_confidence(probability) if probability is not None else 0.0
    elif point == "command":
        r = await squire.guard_command(inp["command"])
        probability = r.probability if r.origin != "code" else None
        predicted = None if (r.origin == "code" or probability is None) else probability >= 0.5
        confidence = truth_confidence(probability) if probability is not None else 0.0
        if r.origin == "code":
            predicted, confidence = "code", 1.0
    elif point == "unsourced":
        r = await squire.review_report(inp["task"], inp["result"])
        probability = r.unsourced if r else None
        predicted = None if probability is None else probability >= 0.5
        confidence = truth_confidence(probability) if probability is not None else 0.0
    elif point == "entity":
        same, probability = await squire.same_entity(
            a=inp["a"],
            context_a=inp.get("context_a", ""),
            b=inp["b"],
            context_b=inp.get("context_b", ""),
        )
        predicted = same if same is not None else (probability >= 0.5)
        confidence = truth_confidence(probability)
    elif point == "facts":
        relation, confidence = await squire.relate_facts(fact_a=inp["fact_a"], fact_b=inp["fact_b"])
        predicted = relation
    elif point == "dependency":
        pairs = await squire.dependency_pairs(
            [
                {"id": "a", "title": inp["a_title"], "goal": inp.get("a_goal", "")},
                {"id": "b", "title": inp["b_title"], "goal": inp.get("b_goal", "")},
            ]
        )
        probability = pairs[("a", "b")]
        predicted = probability >= 0.5
        confidence = truth_confidence(probability)
    elif point == "classify":
        category, probability, _ = await squire.classify(
            field=inp["field"],
            text=inp["text"],
            options=inp["options"],
            context=inp.get("context", ""),
            add_other=inp.get("add_other", True),
        )
        predicted, confidence = category, probability
    elif point == "plan":
        return await _plan(squire, journal, case, before)
    else:
        raise ValueError(f"unknown point: {point}")

    meta = _meta(journal.events[before:])
    decided = predicted is not None and predicted != "review" and predicted != "code"
    correct = None if not decided else (predicted == expected)
    return Row(
        id=str(case["id"]),
        point=point,
        expected=expected,
        predicted=predicted,
        correct=correct,
        decided=decided,
        confidence=float(confidence),
        probability=probability,
        primitive=PRIMITIVE_OF.get(point, "?"),
        **meta,
    )


async def _citation(squire: Squire, claim: str, section: str) -> tuple[str, float]:
    from ..points import citation as cit

    state, qs = cit.questions(claim, section)
    decision = await squire.decide("citation", state, qs)
    verdict, confidence = cit.decide(decision, squire.thresholds, quote_found=True)
    squire.record(decision, verdict=verdict, confidence=confidence)
    return verdict, confidence


async def _plan(
    squire: Squire, journal: MemoryJournal, case: Mapping[str, Any], before: int
) -> dict[str, Any]:
    lines = case["input"]["lines"]
    ids = [str(line["id"]) for line in lines]
    gold = {tuple(e) for e in case["input"]["edges"]}
    pairs = await squire.dependency_pairs(lines)
    raw = {e for e, p in pairs.items() if p >= 0.5}
    clean = build_dag(ids, pairs)
    gold_reduced = transitive_reduction(gold)

    def pr(pred: set, ref: set) -> tuple[float, float]:
        tp = len(pred & ref)
        return (tp / len(pred) if pred else 0.0), (tp / len(ref) if ref else 0.0)

    raw_p, raw_r = pr(raw, gold)
    clean_p, clean_r = pr(clean, gold_reduced)
    closure_p, closure_r = pr(transitive_closure(ids, clean), transitive_closure(ids, gold))
    meta = _meta(journal.events[before:])
    return {
        "id": str(case["id"]),
        "point": "plan",
        "pairs": len(pairs),
        "gold_edges": len(gold),
        "raw": {
            "edges": len(raw),
            "precision": raw_p,
            "recall": raw_r,
            "auc": stats.auc([pairs[e] for e in pairs], [e in gold for e in pairs]),
            "waves": waves(ids, raw),
        },
        "clean": {
            "edges": sorted(clean),
            "precision": clean_p,
            "recall": clean_r,
            "closure_precision": closure_p,
            "closure_recall": closure_r,
            "waves": waves(ids, clean),
            "missing": sorted(gold_reduced - clean),
        },
        "gold_waves": waves(ids, gold),
        **meta,
    }


def _meta(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = [
        e["data"]
        for e in events
        if e["kind"] == "decision" and e["data"].get("provider") not in ("code",)
    ]
    if not decisions:
        return {
            "provider": "code",
            "model": "-",
            "latency_ms": 0,
            "input_tokens": 0,
            "cost_usd": 0.0,
        }
    return {
        "provider": decisions[-1].get("provider", "?"),
        "model": decisions[-1].get("model", "?"),
        "latency_ms": int(sum(d.get("latency_ms", 0) or 0 for d in decisions)),
        "input_tokens": int(sum(d.get("input_tokens", 0) or 0 for d in decisions)),
        "cost_usd": float(sum(d.get("cost_usd", 0.0) or 0.0 for d in decisions)),
    }


async def run_bench(
    cases: Sequence[Mapping[str, Any]],
    decider: Decider,
    *,
    thresholds: Thresholds | None = None,
    concurrency: int = 4,
) -> list[Row | dict[str, Any]]:
    """Every case goes through a fresh squire (no shared query memory) with a shared decider."""
    t = _bench_thresholds(thresholds or Thresholds())
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: Mapping[str, Any]) -> Row | dict[str, Any]:
        async with semaphore:
            journal = MemoryJournal()
            squire = Squire(
                decider,
                thresholds=t.with_(max_decisions=10_000, max_usd=100.0),
                journal=journal,
                brief=str((case.get("input") or {}).get("brief", "")),
            )
            return await _run_case(squire, journal, case)

    return list(await asyncio.gather(*(one(c) for c in cases)))


def _band(confidence: float) -> str:
    for low, high in BANDS:
        if low <= confidence < high:
            return f"{low:.2f}-{min(high, 1.0):.2f}"
    return "?"


def summarize(results: Sequence[Row | dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in results if isinstance(r, Row)]
    plans = [r for r in results if isinstance(r, dict)]
    by_point: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_point[r.point].append(r)

    points: dict[str, Any] = {}
    for point, group in sorted(by_point.items()):
        decided = [r for r in group if r.decided]
        hits = sum(1 for r in decided if r.correct)
        p, low, high = stats.wilson(hits, len(decided))
        entry: dict[str, Any] = {
            "n": len(group),
            "decided": len(decided),
            "coverage": len(decided) / len(group) if group else 0.0,
            "agreement": p,
            "wilson": [low, high],
            "hits": hits,
            "median_latency_ms": stats.median([r.latency_ms for r in group]),
            "bands": _bands(group),
        }
        code_rows = [r for r in group if r.predicted == "code"]
        if code_rows:
            code_correct = sum(1 for r in code_rows if r.expected is True)
            entry["code_denials"] = {
                "n": len(code_rows),
                "correct": code_correct,
                "combined": code_correct + hits,
            }
        binary = [r for r in group if r.probability is not None and isinstance(r.expected, bool)]
        if point in BINARY_POINTS and binary:
            probs = [r.probability for r in binary]  # type: ignore[misc]
            truths = [bool(r.expected) for r in binary]
            entry["auc"] = stats.auc(probs, truths)
            entry["brier"] = stats.brier(probs, truths)
            entry["ece"] = stats.ece(probs, truths)
            entry["at_0.5"] = sum(
                1 for p_, y in zip(probs, truths, strict=True) if (p_ >= 0.5) == y
            )
            entry["n_binary"] = len(binary)
        points[point] = entry

    return {
        "cases": len(results),
        "calls": sum(1 for r in rows if r.provider not in ("code",)),
        "cost_usd": sum(r.cost_usd for r in rows) + sum(p.get("cost_usd", 0.0) for p in plans),
        "input_tokens": sum(r.input_tokens for r in rows)
        + sum(p.get("input_tokens", 0) for p in plans),
        "points": points,
        "bands": _bands(rows),
        "primitives": _by_primitive(rows),
        "plans": plans,
    }


def _bands(rows: Sequence[Row]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        if not r.decided:
            continue
        band = out.setdefault(_band(r.confidence), {"n": 0, "hits": 0})
        band["n"] += 1
        band["hits"] += 1 if r.correct else 0
    return dict(sorted(out.items()))


def _by_primitive(rows: Sequence[Row]) -> dict[str, dict[str, float]]:
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        if r.decided and r.correct is not None:
            groups[r.primitive].append(r)
    out: dict[str, dict[str, float]] = {}
    for prim, group in sorted(groups.items()):
        confs = [r.confidence for r in group]
        corrects = [bool(r.correct) for r in group]
        out[prim] = {
            "n": len(group),
            "agreement": sum(corrects) / len(group),
            "mean_confidence": sum(confs) / len(group),
            "ece": stats.ece(confs, corrects),
        }
    return out


def render_markdown(summary: Mapping[str, Any], *, title: str) -> str:
    head = (
        f"Cases: {summary['cases']} - decision calls: {summary['calls']} - "
        f"input tokens: {summary['input_tokens']} - cost: {summary['cost_usd']:.4f} USD"
    )
    lines = [f"# {title}", "", head, ""]
    lines += [
        "| Point | n | Coverage | Agreement when deciding | Wilson 95 % | Median latency |",
        "|---|---|---|---|---|---|",
    ]
    for point, e in summary["points"].items():
        agreement = f"{e['hits']}/{e['decided']} = {e['agreement']:.0%}"
        wilson = f"[{e['wilson'][0]:.0%}, {e['wilson'][1]:.0%}]"
        latency = f"{e['median_latency_ms']:.0f} ms"
        lines.append(
            f"| {point} | {e['n']} | {e['coverage']:.0%} | {agreement} | {wilson} | {latency} |"
        )
    binary = {p: e for p, e in summary["points"].items() if "auc" in e}
    if binary:
        lines += [
            "",
            "| Binary point | n | Correct at 0.5 | AUC | Brier | ECE |",
            "|---|---|---|---|---|---|",
        ]
        for point, e in binary.items():
            at_half = f"{e['at_0.5']}/{e['n_binary']}"
            metrics = f"{e['auc']:.2f} | {e['brier']:.3f} | {e['ece']:.3f}"
            lines.append(f"| {point} | {e['n_binary']} | {at_half} | {metrics} |")
    for point, e in summary["points"].items():
        code = e.get("code_denials")
        if code:
            lines += [
                "",
                f"`{point}`: the code deny-list fired on {code['n']} cases, "
                f"{code['correct']} of them labelled dangerous; code or model together: "
                f"{code['combined']}/{e['n']} correct.",
            ]
    lines += [
        "",
        "## Agreement by confidence band",
        "",
        "| Band | n | Agreement |",
        "|---|---|---|",
    ]
    for band, b in summary["bands"].items():
        lines.append(f"| {band} | {b['n']} | {b['hits']}/{b['n']} = {b['hits'] / b['n']:.0%} |")
    lines += [
        "",
        "## Calibration by primitive (declared confidence vs. agreement)",
        "",
        "| Primitive | n | Agreement | Mean confidence | ECE |",
        "|---|---|---|---|---|",
    ]
    for prim, e in summary["primitives"].items():
        cells = f"{e['agreement']:.0%} | {e['mean_confidence']:.2f} | {e['ece']:.3f}"
        lines.append(f"| {prim} | {e['n']} | {cells} |")
    for plan in summary.get("plans", []):
        raw, clean = plan["raw"], plan["clean"]
        lines += [
            "",
            f"## Plan `{plan['id']}`: {plan['pairs']} ordered pairs, "
            f"{plan['gold_edges']} reference edges",
            "",
            f"- Raw (p >= 0.5): {raw['edges']} edges, precision {raw['precision']:.0%}, "
            f"recall {raw['recall']:.0%}, AUC {raw['auc']:.2f}; waves {raw['waves']}",
            f"- After dag.py: {len(clean['edges'])} edges, precision {clean['precision']:.0%}, "
            f"recall {clean['recall']:.0%} (closure {clean['closure_precision']:.0%} / "
            f"{clean['closure_recall']:.0%}); waves {clean['waves']}; missing {clean['missing']}",
            f"- Reference waves: {plan['gold_waves']}",
        ]
    return "\n".join(lines) + "\n"


def rows_to_json(results: Sequence[Row | dict[str, Any]]) -> list[dict[str, Any]]:
    return [asdict(r) if isinstance(r, Row) else r for r in results]
