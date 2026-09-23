"""The squire: one decider, one set of thresholds, one journal, one budget.

Every method is a decision point with the same shape:

    build questions -> decide (or not) -> apply the pure policy -> journal -> return

Three guarantees that are not negotiable:

- **Fail-open.** If the decider does not answer, the method returns the default the harness
  had before, and the error is journaled. A provider outage degrades routing; it never
  stops a job.
- **Own budget.** Decisions and dollars per job. A decision costs a ten-thousandth of a
  dollar; a loop without a cap charges anyway.
- **Everything is written.** Each decision goes to the journal with its probabilities,
  confidence, cost, latency and the policy outcome. It is the audit trail and, later, the
  labelled set thresholds are tuned on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .budget import Meter
from .contract import Decider, DeciderUnavailable, Decision, Question, State
from .dag import Edge, build_dag, waves
from .journal import Journal, NullJournal, decision_event
from .points import (
    citation,
    entities,
    graph,
    guard,
    loop,
    memory,
    plan,
    review,
    routing,
    search,
    tools,
    triage,
)
from .policy import Thresholds
from .providers.null import NullDecider
from .text import is_repeat, mention_present, quote_present


@dataclass(frozen=True, slots=True)
class GuardResult:
    denied: bool
    origin: str | None  # "code" | "decider" | None
    reason: str
    probability: float


class Squire:
    def __init__(
        self,
        decider: Decider | None = None,
        *,
        thresholds: Thresholds | None = None,
        journal: Journal | None = None,
        brief: str = "",
        profile: str = "",
    ) -> None:
        self._decider: Decider = decider or NullDecider()
        self._t = thresholds or Thresholds()
        self._journal: Journal = journal or NullJournal()
        self._brief = brief
        self._profile = profile
        self._meter = Meter()
        self._queries: tuple[str, ...] = ()
        self._cap_warned = False

    # --- plumbing --------------------------------------------------------------------

    @property
    def thresholds(self) -> Thresholds:
        return self._t

    @property
    def meter(self) -> Meter:
        return self._meter

    @property
    def journal(self) -> Journal:
        return self._journal

    @property
    def provider(self) -> str:
        return self._decider.name

    async def decide(self, point: str, state: State, questions: Mapping[str, Question]) -> Decision:
        """One decision under the cap and fail-open. Never raises."""
        if not self._meter.within(self._t.max_decisions, self._t.max_usd):
            if not self._cap_warned:
                self._cap_warned = True
                self._journal.record(
                    "warning", {"message": "squire budget exhausted: defaults from here on"}
                )
            return Decision(point, {}, "budget", "-", error="budget exhausted")
        try:
            decision = await self._decider.decide(point, state, questions)
        except DeciderUnavailable as error:
            decision = Decision(point, {}, self._decider.name, "-", error=str(error))
        except Exception as error:  # a provider bug must not take the agent down
            decision = Decision(
                point, {}, self._decider.name, "-", error=f"{error.__class__.__name__}: {error}"
            )
        self._meter = self._meter.add(decision.cost_usd)
        return decision

    def record(self, decision: Decision, **outcome: Any) -> None:
        self._journal.record("decision", decision_event(decision, outcome))

    # --- decision points -------------------------------------------------------------

    async def route_task(
        self, task: str, *, requested: str | None = None, default: routing.Tier = "default"
    ) -> routing.Routing:
        """Which tier of model a delegated task deserves."""
        state, qs = routing.questions(task, brief=self._brief, profile=self._profile)
        decision = await self.decide("routing", state, qs)
        result = routing.decide(decision, self._t, default=default)
        self.record(decision, requested=requested, chosen=result.tier, reason=result.reason)
        return result

    async def route_search(
        self, query: str, *, cheap_available: bool = False
    ) -> search.SearchRoute:
        """Where a query goes. Remembers earlier queries to catch repeats."""
        repeat = is_repeat(query, self._queries)
        state, qs = search.questions(query, previous=self._queries, brief=self._brief)
        decision = await self.decide("search", state, qs)
        result = search.decide(
            decision, self._t, cheap_available=cheap_available, repeat_by_code=repeat
        )
        if result.route != "cut":
            self._queries = (*self._queries, query)
        self.record(decision, route=result.route, category=result.category, reason=result.reason)
        return result

    async def triage_page(
        self, *, purpose: str, title: str = "", url: str = "", text: str
    ) -> triage.Triage:
        state, qs = triage.questions(purpose=purpose, title=title, url=url, text=text)
        decision = await self.decide("triage", state, qs)
        result = triage.decide(decision, self._t)
        self.record(
            decision,
            url=url,
            keep=result.keep,
            reason=result.reason,
            source_kind=result.source_kind,
        )
        return result

    async def triage_results(
        self, results: Sequence[Mapping[str, Any]], *, purpose: str
    ) -> list[dict[str, Any]]:
        """Filter and reorder search results: evidence first."""
        triaged = await asyncio.gather(
            *(
                self.triage_page(
                    purpose=purpose,
                    title=str(r.get("title", "")),
                    url=str(r.get("url", "")),
                    text=str(r.get("text", "")),
                )
                for r in results
            )
        )
        kept = [(tr, r) for tr, r in zip(triaged, results, strict=True) if tr.keep]
        kept.sort(key=lambda pair: (pair[0].evidence, pair[0].relevance), reverse=True)
        return [
            {**dict(r), "source_kind": tr.source_kind, "evidence": tr.evidence} for tr, r in kept
        ]

    async def select_tools(
        self,
        *,
        purpose: str,
        catalog: Sequence[Mapping[str, Any]],
        clues: str = "",
        always: Iterable[str] = (),
    ) -> tools.Selection:
        """Which groups of a tool catalog the model's call should carry. Never empty.

        Large catalogs are asked in chunks, in parallel, and merged before the policy runs
        once over the whole catalog. `always` groups are pinned by code, not by the model.
        """
        groups = [dict(g) for g in catalog]
        if not groups:
            return tools.Selection((), (), "empty catalog", {})
        chunks = [
            groups[i : i + tools.GROUPS_PER_CALL]
            for i in range(0, len(groups), tools.GROUPS_PER_CALL)
        ]
        decisions = await asyncio.gather(
            *(
                self.decide("tools", *tools.questions(purpose=purpose, catalog=c, clues=clues))
                for c in chunks
            )
        )
        probs: dict[str, float | None] = {}
        for d, c in zip(decisions, chunks, strict=True):
            probs.update(tools.probabilities_of(d, c))
        selection = tools.select(
            probs, self._t, always=always, failed=all(d.failed for d in decisions)
        )
        for d in decisions:
            self.record(
                d, kept=len(selection.keep), dropped=len(selection.dropped), reason=selection.reason
            )
        return selection

    async def verify_citation(
        self, *, claim: str, quote: str, source: str
    ) -> tuple[citation.Verdict, float]:
        """Literal presence in code; meaning in the decider; doubt to review."""
        found = quote_present(quote, source)
        if not found:
            decision = Decision("citation", {}, "code", "-")
            verdict, confidence = citation.decide(decision, self._t, quote_found=False)
            self.record(decision, verdict=verdict, confidence=confidence)
            return verdict, confidence
        state, qs = citation.questions(claim, source)
        decision = await self.decide("citation", state, qs)
        verdict, confidence = citation.decide(decision, self._t, quote_found=True)
        self.record(decision, verdict=verdict, confidence=confidence)
        return verdict, confidence

    async def evaluate_plan(
        self, lines: Sequence[Mapping[str, Any]], *, findings: str = ""
    ) -> list[dict[str, Any]]:
        """Score a plan's lines and, for small plans, add dependencies and parallel waves."""
        titles = [str(line.get("title", "")) for line in lines]

        async def one(index: int, line: Mapping[str, Any]) -> dict[str, Any]:
            others = [t for i, t in enumerate(titles) if i != index]
            state, qs = plan.line_questions(
                line, brief=self._brief, others=others, findings=findings
            )
            decision = await self.decide("plan_line", state, qs)
            ev = plan.decide_line(decision, self._t)
            result = {
                "title": titles[index],
                "priority": ev.priority,
                "parallel": ev.parallel,
                "saturated": ev.saturated,
                "tier": ev.tier,
                "source_kind": ev.source_kind,
                "reason": ev.reason,
            }
            self.record(decision, **result)
            return result

        evaluated = list(await asyncio.gather(*(one(i, line) for i, line in enumerate(lines))))
        if 2 <= len(lines) <= plan.MAX_LINES_FOR_DAG:
            edges, layers = await self.dependencies(
                [{**dict(line), "id": str(line.get("title", ""))} for line in lines]
            )
            depends: dict[str, list[str]] = {}
            for a, b in edges:
                depends.setdefault(b, []).append(a)
            wave_of = {n: i + 1 for i, layer in enumerate(layers) for n in layer}
            evaluated = [
                {
                    **e,
                    "depends_on": sorted(depends.get(e["title"], [])),
                    "wave": wave_of.get(e["title"], 1),
                    "parallel": e["title"] not in depends,
                }
                for e in evaluated
            ]
        return sorted(evaluated, key=lambda e: (e.get("wave", 1), -e["priority"]))

    async def dependency_pairs(self, lines: Sequence[Mapping[str, Any]]) -> dict[Edge, float]:
        """Ask the decider about every ordered pair. Raw probabilities; the DAG is built later."""
        ids = [str(line.get("id") or line.get("title", "")) for line in lines]
        by_id = {i: line for i, line in zip(ids, lines, strict=True)}

        async def pair(a: str, b: str) -> tuple[Edge, float]:
            state, qs = plan.dependency_questions(
                a_title=str(by_id[a].get("title", "")),
                a_goal=str(by_id[a].get("goal", "")),
                b_title=str(by_id[b].get("title", "")),
                b_goal=str(by_id[b].get("goal", "")),
            )
            decision = await self.decide("dependency", state, qs)
            p = decision.answer("b_needs_a").truth
            self.record(decision, a=a, b=b, probability=p)
            return (a, b), (p if p is not None else 0.0)

        pairs = await asyncio.gather(*(pair(a, b) for a in ids for b in ids if a != b))
        return dict(pairs)

    async def dependencies(
        self, lines: Sequence[Mapping[str, Any]]
    ) -> tuple[set[Edge], list[list[str]]]:
        """Clean DAG of a plan: pairs to the decider, cycles and transitives to code."""
        ids = [str(line.get("id") or line.get("title", "")) for line in lines]
        pairs = await self.dependency_pairs(lines)
        edges = build_dag(ids, pairs)
        layers = waves(ids, edges)
        self._journal.record(
            "decision",
            {
                "point": "dag",
                "provider": "code",
                "model": "-",
                "cost_usd": 0.0,
                "outcome": {"edges": sorted(edges), "waves": layers},
            },
        )
        return edges, layers

    async def review_report(self, task: str, result: str) -> review.Review | None:
        state, qs = review.questions(task, result)
        decision = await self.decide("review", state, qs)
        outcome = review.decide(decision, self._t)
        self.record(decision, message=outcome.message if outcome else None)
        return outcome

    async def guard_command(
        self, command: str, *, environment: Mapping[str, Any] | None = None
    ) -> GuardResult:
        """Deny-list in code first; the decider can add a denial, never an approval."""
        why = guard.code_denial(command)
        if why:
            decision = Decision("guard", {}, "code", "-")
            self.record(decision, command=command[:200], denied=True, origin="code", reason=why)
            return GuardResult(True, "code", why, 1.0)
        state, qs = guard.questions(command, environment=environment)
        decision = await self.decide("guard", state, qs)
        dangerous, p = guard.decide(decision, self._t)
        reason = f"the decision model flags it as dangerous ({p:.2f})" if dangerous else ""
        self.record(
            decision,
            command=command[:200],
            denied=dangerous,
            origin="decider" if dangerous else None,
            probability=p,
        )
        return GuardResult(dangerous, "decider" if dangerous else None, reason, p)

    async def same_entity(
        self, *, a: str, context_a: str = "", b: str, context_b: str = ""
    ) -> tuple[bool | None, float]:
        state, qs = entities.alignment_questions(a=a, context_a=context_a, b=b, context_b=context_b)
        decision = await self.decide("entity", state, qs)
        same, p = entities.decide_alignment(decision, self._t)
        self.record(decision, a=a[:120], b=b[:120], same=same, probability=p)
        return same, p

    async def relate_facts(self, *, fact_a: str, fact_b: str) -> tuple[str | None, float]:
        state, qs = entities.fact_questions(fact_a=fact_a, fact_b=fact_b)
        decision = await self.decide("facts", state, qs)
        relation, confidence = entities.decide_facts(decision, self._t)
        self.record(decision, relation=relation, confidence=confidence)
        return relation, confidence

    async def classify(
        self,
        *,
        field: str,
        text: str,
        options: Mapping[str, Any],
        context: str = "",
        add_other: bool = True,
    ) -> tuple[str | None, float, dict[str, float]]:
        state, qs = entities.classification_questions(
            field=field, text=text, options=options, context=context, add_other=add_other
        )
        decision = await self.decide("classify", state, qs)
        category, p, dist = entities.decide_classification(decision, self._t, options=options)
        self.record(decision, field=field, category=category, probability=p)
        return category, p, dist

    # --- fetch-heavy retrieval, memory and graph ------------------------------------

    async def triage_redundant(self, *, purpose: str, text: str, known: str) -> triage.Redundancy:
        """Does this page repeat what the agent already holds? Drops only on a confident yes.

        The lever the end-to-end A/B could not exercise, because its agent fetched one or
        two documents per task. It bites when a job gathers many sources about one event.
        """
        state, qs = triage.redundancy_questions(purpose=purpose, text=text, known=known)
        decision = await self.decide("redundant_page", state, qs)
        result = triage.decide_redundancy(decision, self._t)
        self.record(decision, drop=result.drop, reason=result.reason)
        return result

    async def remember(self, fact: str, *, source: str = "") -> memory.Write:
        """Is this worth writing to long-term memory? Stores only on a confident yes."""
        state, qs = memory.write_questions(fact=fact, brief=self._brief, source=source)
        decision = await self.decide("memory_write", state, qs)
        result = memory.decide_write(decision, self._t)
        self.record(decision, store=result.store, reason=result.reason)
        return result

    async def reconcile(
        self, *, new: str, stored: str, newer: bool | None = None
    ) -> memory.Reconciliation:
        """What to do with a candidate memory that touches a stored one.

        `newer` comes from the harness's timestamps, never from the decider: this model
        class reads dates as text, and replacing the wrong way round is a silent loss.
        Without it a real collision is flagged, not resolved.
        """
        state, qs = memory.collision_questions(new=new, stored=stored)
        decision = await self.decide("memory_collision", state, qs)
        result = memory.decide_collision(decision, self._t, newer=newer)
        self.record(decision, action=result.action, reason=result.reason)
        return result

    async def needs_recall(self, turn: str, *, topics: str = "") -> memory.Recall:
        """Does this turn need a memory lookup at all? Skips only on a confident no."""
        state, qs = memory.recall_questions(turn=turn, topics=topics)
        decision = await self.decide("recall", state, qs)
        result = memory.decide_recall(decision, self._t)
        self.record(decision, look=result.look, reason=result.reason)
        return result

    async def gate_extraction(
        self, *, chunk: str, looking_for: str, kinds: Sequence[str] = ()
    ) -> graph.Gate:
        """Is this chunk worth a generative extraction call? Skips only on a confident no."""
        state, qs = graph.gate_questions(chunk=chunk, looking_for=looking_for, kinds=kinds)
        decision = await self.decide("extract_gate", state, qs)
        result = graph.decide_gate(decision, self._t)
        self.record(decision, extract=result.extract, reason=result.reason)
        return result

    async def verify_edge(
        self, *, subject: str, relation: str, obj: str, text: str
    ) -> graph.EdgeCheck:
        """Does the text state this triple? Mentions in code, meaning in the decider."""
        found = mention_present(subject, text) and mention_present(obj, text)
        if not found:
            decision = Decision("edge", {}, "code", "-")
            result = graph.decide_edge(decision, self._t, mentions_found=False)
            self.record(decision, verdict=result.verdict, reason="a mention is not in the text")
            return result
        state, qs = graph.edge_questions(subject=subject, relation=relation, obj=obj, text=text)
        decision = await self.decide("edge", state, qs)
        result = graph.decide_edge(decision, self._t, mentions_found=True)
        self.record(decision, verdict=result.verdict, stated=result.stated)
        return result

    async def check_loop(
        self, *, goal: str, done: str, pending: str = "", checks: Sequence[str] = ()
    ) -> loop.LoopAdvice:
        """Is the goal already met, or is this check a repeat? Advises; never denies."""
        state, qs = loop.questions(goal=goal, done=done, pending=pending, checks=checks)
        decision = await self.decide("loop", state, qs)
        result = loop.decide(decision, self._t)
        self.record(decision, message=result.message or None)
        return result
