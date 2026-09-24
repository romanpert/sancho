<div align="center">

<img src="https://raw.githubusercontent.com/romanpert/sancho/main/docs/assets/logo.png"
     alt="Sanchopanza" width="180">

# Sanchopanza

**A calibrated, non-generative decision layer for LLM agent harnesses.**

[![PyPI](https://img.shields.io/pypi/v/sanchopanza.svg)](https://pypi.org/project/sanchopanza/)
[![Python](https://img.shields.io/pypi/pyversions/sanchopanza.svg)](https://pypi.org/project/sanchopanza/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![CI](https://github.com/romanpert/sancho/actions/workflows/ci.yml/badge.svg)](https://github.com/romanpert/sancho/actions/workflows/ci.yml)
[![Paper](https://img.shields.io/badge/paper-working%20draft-informational)](docs/paper.md)

*The knight thinks. The squire reads.*

</div>

---

## The idea in one paragraph

An agent takes two kinds of decision. The **substantive** ones, what to investigate, what the
evidence means, how to write it up, are what you pay the large model for. The **procedural**
ones, which model size this subtask deserves, whether this search repeats an earlier one,
whether this page is worth reading, whether this citation holds, whether this shell command
is safe, happen dozens to hundreds of times per job, get paid at the large model's price, and
leave no trace of why they were taken. Sanchopanza moves those to a model that returns a
typed choice, a scale position or a probability, **never text**, at 29 millionths of a dollar
and a quarter of a second. It attaches through the hooks and tools your harness already has.

```bash
pip install sanchopanza[jev]     # TypeSafe Jev over HTTP
pip install sanchopanza[mcp]     # expose the decision points as MCP tools
pip install sanchopanza          # core only: recorded, null, local and LLM providers
```

Distribution, import and command are all `sanchopanza`; `sancho` is a short alias for the
command. Python 3.11+. No required dependencies.

---

## 60-second start

```python
import asyncio
from sanchopanza import JsonlJournal, Squire, Thresholds
from sanchopanza.providers import create

squire = Squire(
    create("jev"),                   # reads TYPESAFE_API_KEY
    thresholds=Thresholds(),         # the measured defaults
    journal=JsonlJournal("journal.jsonl"),
    brief="Defamation litigation in the Dominican Republic, 2020-2026",
)

async def main():
    route = await squire.route_task("List the rulings that mention defamation since 2020")
    print(route.tier, route.reason)          # light   complexity 0.05 at confidence 0.93

    verdict, confidence = await squire.verify_citation(
        claim="The court ordered a fine of 500,000 pesos.",
        quote="lo condena al pago de una indemnizacion de RD$500.000",
        source="FALLA: declara culpable al imputado ... y lo condena al pago de una "
               "indemnizacion de RD$500.000 a favor del querellante.",
    )
    print(verdict, confidence)               # supported 0.98

asyncio.run(main())
```

No key? `create("null")` makes every method return its default and the agent behaves exactly
as it did before. That is the point: **the squire can only improve an agent, never stop one.**

---

## What it decides

| Method | Decides | Measured |
|---|---|---|
| `route_task` | Which model tier a subtask deserves | 17/20 raw; **11/11** when acting above 0.75 confidence; a small LLM got 8/20 |
| `route_search` | Repeat, cheap engine, or the paid one | **17/18** |
| `triage_page` | Whether a page enters the context, and whether it carries injected instructions | relevance 14/16; injection **28/28, AUC 1.00** against a regex 23/28 |
| `verify_citation` | supported / contradicted / unsupported / fabricated / review | **19/20**; with numbers 23/24 |
| `evaluate_plan` | Priority, saturation, tier, dependencies as a DAG with parallel waves | pairwise **20/20**; full DAG 100 % precision, 88 % recall after code cleanup |
| `review_report` | Whether a subagent's report names its sources | **21/22** |
| `guard_command` | Adds a denial on a dangerous shell command, never an approval | 29/32 alone; **31/32 with the code deny-list, zero false positives** |
| `same_entity` | Whether two mentions are the same real-world entity | **24/24** |
| `relate_facts` | agree / conflict / unrelated | 16/20, not yet integrated |
| `classify` | Free text into a closed vocabulary, with abstention | **80-85 %** against independent labels; majority baseline 43-62 % |
| `select_tools` | Which groups of a large tool catalog a request needs | accuracy not yet measured; **the wiring is**, and it is the one that can cost you money: [read this first](benchmarks/cache/results/summary.md) |

Added in 0.2.0, first run measured on 124 new cases
([results](docs/results/2026-09-24-new-points/summary.md)):

| Method | Decides | Measured |
|---|---|---|
| `check_loop` | Whether the goal is already met, or a check repeats one already run | **14/14** and **12/12**, AUC 1.00. Attacks the largest measured waste in an agent loop: 18x the clean-run cost, no success gain |
| `remember` | Whether a fact is worth writing to long-term memory | **16/16**, AUC 1.00 |
| `reconcile` | Whether a new fact contradicts, duplicates or complements a stored one | **14/16**; recency stays in code, because dates are the model's declared weakness |
| `needs_recall` | Whether a turn needs a memory lookup at all | **14/14**, AUC 1.00, ECE 0.051 |
| `gate_extraction` | Whether a chunk is worth a generative extraction call | **15/16**, AUC 1.00 |
| `verify_edge` | Whether the text states a proposed triple, in that direction | 15/17 when deciding; **8 edges committed, 0 of them wrong** |
| `triage_redundant` | Whether a page repeats what the agent already holds | **14/16**, 15/16 at a plain 0.5 cut, AUC 1.00 |

> **What that run found, and what it turned out to be.** Across the six binary points the
> model is right **86 times out of 88** at a plain 0.5 cut, with **AUC 1.00 on every one**:
> no error is an ordering error. Under the shipped policy it was 78 of 88, and the eight
> lost decisions looked like conservative thresholds. They were not. For a Truth answer from
> this model, `confidence` is exactly `|2p - 1|` - 651 recorded answers, zero deviation - so
> a policy asking for both `p >= 0.70` and `confidence >= 0.60` was asking for `p >= 0.80`,
> and the threshold named in the configuration was not the one in force. Removing the
> redundant gate changed **no threshold value** and closed the gap to three decisions:
> **85 of 88**.

Full method, intervals and caveats: [the paper](docs/paper.md). Benches and how to run them:
[docs/benches.md](docs/benches.md).

> **The result that matters is not accuracy, it is separation.** 131 of 132 decisions above
> 0.75 confidence were right, against 11 of 24 below it. Thirteen of the model's fourteen
> errors carried confidence below 0.75. A small LLM's self-reported confidence did not
> separate its errors at all. That is what lets a policy act only when confident and fall back
> to the harness default otherwise.

---

## What it costs, honestly

| | |
|---|---|
| One decision | **29 millionths of a dollar**, output included, because this model's output is free |
| The same tokens on Claude Sonnet 5, input only | **48x** more |
| The same tokens as a Sonnet 5 **cache read** (0.1x input) | **4.8x** more, and this is the honest comparison inside a warm loop |
| Measured against Claude Haiku 4.5, tool-forced, same cases | **49x cheaper, 3x faster**, comparable accuracy |
| Against a hosted evaluation meter (Azure, Vertex legacy), per 1,000 judgments | 0.029 USD against about 42 USD: **~1,450x** |

**There is no headline saving percentage on this page, and that is deliberate.** We ran the
end-to-end A/B ([benchmarks/ab](benchmarks/ab)) instead of guessing. Across 64 paired runs,
two retrieval conditions and two document sizes, page triage **did not measurably change
cost** (every interval spans zero) and added 11 to 16 % wall time (both intervals exclude
zero). It lost no answers. The reason is visible in the runs: our tasks fetched one or two
documents each, and the lever only bites when an agent fetches many and most are useless.

So: **add Sanchopanza for the safety and quality decisions, which are measured, not for the
bill, which we could not demonstrate in our own agent.** The break-even arithmetic and the
fetch-heavy experiment that would settle the cost question are in
[docs/savings.md](docs/savings.md) and [benchmarks/](benchmarks/).

**Where it does pay, and why the A/B could not see it.** A cheap decision pays reliably when
it *replaces* a call some model was going to make anyway (verify this citation, match this
pair, check this triple, screen this page), because then the saving is a price ratio and not
a bet on the workload's shape. It pays unreliably when it tries to keep tokens out of a
context, which is what our A/B measured. And it pays a third way that is not a saving at
all: at 29 millionths a decision, checks that were too expensive to run on everything become
cheap enough to run on everything. The full argument, the catalog of levers ranked by how
sure we are, and the four things you should *not* use a decision model for, are in
**[docs/where-it-pays.md](docs/where-it-pays.md)**.

**And one way to lose money with it.** Tool definitions sit at the front of the prompt
prefix, so rewriting them invalidates the tools, system and message caches at once. Measured
over 8 turns on Claude Sonnet 5: narrowing the catalog **once** is 43 % cheaper than not
narrowing, narrowing it on alternate turns is 14 % *dearer* than not narrowing, and a
selector that picks a different subset every turn reads **nothing** from cache and costs
4.15x the one that decided once ([benchmarks/cache](benchmarks/cache/results/summary.md)).
Same decision, different moment, opposite sign.

---

## Architecture

```mermaid
flowchart LR
    subgraph Knight["Knight: the large model"]
        P[plan] --> A[act: tool call] --> O[observe] --> P
    end
    subgraph Harness["Your harness"]
        PRE[PreToolUse]
        POST[PostToolUse]
        MCP[MCP tools]
    end
    subgraph SP["Sanchopanza"]
        G[Guardian<br/>tool call -> verdict] --> S[Squire<br/>points + policy + budget + journal]
        S --> D{{Decider contract}}
    end
    D --> J[Jev / TypeSafe]
    D --> L[Local classifier / vision]
    D --> M[LLM forced to a schema]
    D --> R[Recorded fixture]
    A -.-> PRE --> G
    O -.-> POST --> G
    A -.-> MCP --> S
    S --> E[(journal: one event per decision)]
```

| Module | Holds |
|---|---|
| `sanchopanza.contract` | `Choice`, `Score`, `Truth` questions in; `Answer` with probabilities and confidence out; the `Decider` protocol |
| `sanchopanza.points` | The questions of each decision point, verbatim as measured, plus a pure policy function per point |
| `sanchopanza.squire` | One decider, one `Thresholds`, one journal, one budget. Fail-open, capped, traced |
| `sanchopanza.harness` | `Guardian` (tool call in, verdict out) and the per-harness adapters |
| `sanchopanza.providers` | `jev`, `recorded`, `null`, `llm`, `local`, plus `FallbackDecider` and `RoutedDecider` |
| `sanchopanza.eval` | Bench runner and statistics, in plain Python: Wilson, bootstrap, McNemar, AUC, Brier, ECE |

### Four invariants

1. **Fail open.** No provider, no key, exhausted budget, provider bug: every policy returns
   the default the harness had before. `Squire.decide` never raises.
2. **Asymmetry.** The direction whose error the user sees needs more confidence. Downgrade a
   model at 0.75, upgrade at 0.60. Drop a page only on explicit low relevance; in doubt it
   enters. Emit a citation verdict at 0.80, else abstain. The guard denies, never approves.
3. **Trace.** One journal event per decision, with probabilities, confidence, cost, latency
   and outcome. Audit trail first, labelled dataset later.
4. **Cache-safe by construction.** A decision acts only where acting cannot invalidate a
   cached prefix: before the first request of a session, on content about to be appended, or
   inside a tool the agent called anyway. Never by rewriting `tools`, `system` or history
   mid-session. This one is measured, not assumed: getting it wrong costs 4.15x
   ([benchmarks/cache](benchmarks/cache/results/summary.md)).

More: [docs/architecture.md](docs/architecture.md).

---

## Attach it to a harness

| Harness | How | Status |
|---|---|---|
| **Claude Agent SDK** | `hooks=hook_matchers(guardian)` | Hook shapes tested |
| **Claude Code** | A command hook pointed at `sanchopanza hook` | Tested end to end |
| **MCP client** (Cursor, Codex, Copilot, Hermes, yours) | `build_server(squire).run()` | Parsers tested |
| **OpenAI Agents SDK** | `tool_guardrail(guardian)` | Shape tested |
| **LangChain / LangGraph** | `ToolSelectMiddleware(squire)` | Shape tested |
| **Anything else** | `await guardian.before_tool(ToolCall(name, args))` returns allow, deny with a reason, or rewrite with new arguments | |

<details>
<summary><b>Claude Agent SDK</b></summary>

```python
from claude_agent_sdk import ClaudeAgentOptions
from sanchopanza.harness import Guardian, HarnessConfig
from sanchopanza.harness.claude_agent_sdk import hook_matchers

guardian = Guardian(squire, HarnessConfig(
    tiers={"light": "researcher-light", "default": "researcher", "deep": "researcher-deep"},
    # A probe, never a constant: it answers "does that engine exist and answer, right now".
    # A flag that is always true routes work into a hole, and nothing fails. See
    # docs/where-it-pays.md, section 5.
    cheap_search_available=search_engine.reachable,
))
options = ClaudeAgentOptions(hooks=hook_matchers(guardian), ...)
```
</details>

<details>
<summary><b>Claude Code</b> (<code>.claude/settings.json</code>)</summary>

```json
{"hooks": {
  "PreToolUse":  [{"matcher": "Agent|WebSearch|Bash",
                   "hooks": [{"type": "command", "command": "sanchopanza hook"}]}],
  "PostToolUse": [{"matcher": "Agent",
                   "hooks": [{"type": "command", "command": "sanchopanza hook"}]}]
}}
```

Configure with `TYPESAFE_API_KEY`, `SANCHO_PROVIDER`, `SANCHO_TIERS`, `SANCHO_JOURNAL`.
See [examples/claude_code](examples/claude_code/).
</details>

<details>
<summary><b>MCP server</b></summary>

```python
from sanchopanza.harness.mcp import build_server
build_server(squire).run()
```

Tools: `verify_citation`, `evaluate_plan`, `align_entities`, `classify_field`, `triage_text`.
</details>

Details per harness, including what is tested and what is not:
[docs/adapters.md](docs/adapters.md).

---

## Swap the model

The contract is five lines, so a provider is one file.

```python
from sanchopanza import answers
from sanchopanza.providers import FallbackDecider, LocalDecider, create

local = LocalDecider({                                  # your classifier, on your hardware
    "injection": lambda state, q: answers.truth(clf.predict_proba(state["text"])),
})
squire = Squire(FallbackDecider([local, create("jev")]))  # local first, hosted for the rest
```

`RoutedDecider({"guard": on_prem}, default=hosted)` keeps one decision point in your building.
`LLMDecider(anthropic_completer(...))` forces any chat model into the same schema, with the
caveat, measured, that an LLM's self-reported confidence does not separate its errors. Vision
models plug in through `LocalDecider` with the image reference in the state. Third-party
packages register providers under the `sanchopanza.providers` entry-point group.

Writing one: [docs/providers.md](docs/providers.md).

---

## Measure before you trust

```bash
sanchopanza bench benches/*.jsonl --provider recorded --fixture fixtures/public-benches.jsonl
sanchopanza bench mycases.jsonl --provider jev --record fixtures/mine.jsonl --out results/today
```

The first command replays a real run from a recording, costs nothing and reproduces every
number in the paper. Both print agreement when deciding, coverage, Wilson intervals, AUC,
Brier, expected calibration error, agreement by confidence band and calibration by primitive.

**The rule for thresholds:** one moves when that decision point has 50 cases, a second
annotator, and a confidence-band table that justifies the move. The shipped defaults were
fixed before the runs that measured them and have not been tuned on the results.

---

## What it is not

- **Not an arithmetic engine.** It does not count or compare numbers. Code does that for free
  and correctly.
- **Not a security boundary.** The decision model is itself vulnerable to instructions
  injected into its state. It may add a denial on top of a deterministic list; it never grants
  permission.
- **Not an explainer.** The audit trail is probabilities, not prose.
- **Not a silver bullet for cost.** See the A/B. It pays when documents are large or
  retrieval is noisy, and it costs latency always.
- **Not a competitor to your harness's own tool search.** Anthropic's appends schemas instead
  of swapping them, so it keeps the cache; ours would have to rewrite `tools`. Where a tool
  search exists, use it, and keep the squire for decisions it does not make.
- **Not a substitute for a probe.** It chooses between the options you tell it exist. If one
  of them does not, it will route work into the hole confidently, and nothing will fail.

---

## Repository

```
src/sanchopanza/       the package
benches/               public benches: core 74, safety 106, graph 64 + one plan,
                       and 124 more for memory, graph building, redundancy and the loop
fixtures/              two recorded real runs, so tests and CI cost nothing
benchmarks/ab/         the end-to-end A/B: corpus, tasks, runner, results
benchmarks/cache/      what narrowing a tool catalog costs, per turn against once
skills/sanchopanza/    a skill for coding agents that wire this in
docs/paper.md          the working paper
docs/savings.md        what it costs, and the break-even arithmetic
docs/where-it-pays.md  which decisions are worth taking, ranked by how sure we are
docs/architecture.md   diagrams and the invariants
docs/adapters.md       one section per harness
docs/providers.md      how to write a provider
docs/governance.md     branch protection, PyPI trusted publishing, releasing
examples/              Claude Code, Claude Agent SDK, MCP, a local provider
tests/                 no test calls a paid API
```

Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). Cases with labels are worth more than
features.

---

<div align="center">

**Apache 2.0**, which adds an express patent grant on top of a permissive licence.

Named after the squire who keeps his feet on the ground while the knight sees giants.

</div>
