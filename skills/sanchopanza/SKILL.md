---
name: sanchopanza
description: Add a calibrated, non-generative decision layer to an agent harness with the sanchopanza package. Use when routing between model tiers, triaging fetched pages before they enter context, detecting prompt injection, verifying citations, guarding shell commands, aligning entities, classifying into a closed vocabulary, ordering a plan as a DAG, or selecting tools from a large catalog. Also use when deciding whether a small decision model is worth adding at all, or when choosing thresholds.
---

# Wiring a squire into an agent

`sanchopanza` puts the procedural decisions of an agent loop on a model that returns a
typed choice, a scale position or a probability, never text. The knight thinks; the squire
reads. Install with `pip install sanchopanza[jev]`, import as `sanchopanza`.

Everything below has a measurement behind it or says that it does not.

## 1. Decide whether it is worth it at all

It is worth it when the loop makes the same small judgment many times per job, and each one
is currently paid at the large model's price inside its context, with no trace of why.

It is **not** worth it when:

- The judgment needs arithmetic, date comparison or counting. The model class reads numbers
  as text. Code does this for free and correctly.
- Something deterministic already decides it. A literal quote match, token overlap between
  queries, a deny-list regex, the transitive reduction of a graph. Those run first, cost
  nothing and never drift.
- The decision is the only barrier before a dangerous action. The decision model is itself
  vulnerable to instructions injected into its state. It may add a denial; it must never
  grant permission.
- The answer has to be explained in prose. The audit trail here is probabilities.
- **The harness already has a better mechanism.** If it offers a server-side tool search, use
  that instead of `select_tools`: it appends schemas rather than swapping them, so it keeps
  the prompt cache, and it is not metered.
- **The thing you would be filtering is mostly noise.** Below roughly 17 % precision in
  whatever proposes the candidates, a filter adds nothing measurable. Measure the generator
  before you build the filter.

**Ask where it will act before you ask how accurate it is.** A decision is worth what its
attachment point lets it be worth. Measured in this repository: narrowing a tool catalog once
per session is 43 % cheaper, and the same narrowing done afresh every turn costs 4.15x,
because rewriting `tools` invalidates the whole prompt cache. Outside it: Meta moved the same
static analysis, with the same false-positive rate, from batch to diff time and its fix rate
went from near zero to over 70 %.

Cost check before you build: one decision is about 29 millionths of a dollar, and there are
three different ways that can be worth something. It **substitutes** for a call some model
was going to make anyway (verify this citation, match this pair, check this triple): the
saving is a price ratio, 24x to 119x by list price, and it is the only one of the three whose
arithmetic is safe. It **avoids** tokens entering a context: worth less than it looks,
because inside a warm loop those tokens are priced at the cache-read rate of 0.1x, so the
multiple is 4.8x on a Sonnet-class model, not 48x. Or it makes a check **affordable** that
was previously skipped, which is a quality result and should never be reported as a saving.

Break-evens, measured: a fetched page pays for its own triage above roughly 60 tokens on a
Sonnet-class orchestrator; a delegated subtask pays for its own routing above roughly 75.
See `docs/savings.md` and `docs/where-it-pays.md` in the repository.

## 2. Pick the decision point

| You want to | Method | Measured |
|---|---|---|
| Send a subtask to a cheaper or deeper model | `route_task` | 17/20 raw; 11/11 when acting at confidence >= 0.75; a small LLM got 8/20 |
| Stop a repeated search, or send it to a free engine | `route_search` | 17/18 |
| Keep an irrelevant or injected page out of the context | `triage_page` | 14/16 relevance; injection 28/28, AUC 1.00, regex 23/28 |
| Check that a source supports a claim | `verify_citation` | 19/20; with numbers 23/24 |
| Prioritize a round's lines and get parallel waves | `evaluate_plan` | pairwise 20/20; full DAG 100 % precision, 88 % recall after code cleanup |
| Notice a subagent report that states facts without sources | `review_report` | 21/22 |
| Add a denial on a dangerous shell command | `guard_command` | 29/32 alone; 31/32 with the code deny-list, zero false positives |
| Decide whether two mentions are the same entity | `same_entity` | 24/24 |
| Put free text into a closed vocabulary | `classify` | 80-85 % against independent labels, majority baseline 43-62 % |
| Narrow a large tool catalog, **once per session** | `select_tools` | accuracy not measured; the wiring is, and doing it per turn costs 4.15x |
| Stop a loop that has already finished, or a check that repeats one | `check_loop` | 14/14 and 12/12, AUC 1.00 |
| Decide whether a fact is worth writing to long-term memory | `remember` | 16/16 at a 0.5 cut, 12/16 under shipped thresholds |
| Reconcile a new fact against a stored one | `reconcile` | 14/16; recency comes from your timestamps, never from the model |
| Skip a memory lookup a turn does not need | `needs_recall` | 14/14, AUC 1.00 |
| Skip a generative extraction call on a chunk with nothing in it | `gate_extraction` | 15/16, AUC 1.00 |
| Check a proposed triple before it enters a graph | `verify_edge` | 8 committed, 0 wrong, on 20 cases |
| Drop a source that repeats what you already have | `triage_redundant` | 15/16 at a 0.5 cut, 11/16 under shipped thresholds |

## 3. Wire it in

Hooks for what happens without the model asking; tools for what it asks on purpose.

```python
from sanchopanza import Squire, Thresholds, JsonlJournal
from sanchopanza.providers import create
from sanchopanza.harness import Guardian, HarnessConfig

squire = Squire(
    create("jev"),                      # or "null", "recorded", "llm", "local"
    thresholds=Thresholds(),            # the measured defaults
    journal=JsonlJournal("journal.jsonl"),
    brief="what this job is about",
)
guardian = Guardian(squire, HarnessConfig(tiers={"light": "...", "deep": "..."}))
```

- **Claude Agent SDK**: `from sanchopanza.harness.claude_agent_sdk import hook_matchers` and
  pass `hooks=hook_matchers(guardian)`.
- **Claude Code**: point a `PreToolUse` / `PostToolUse` command hook at `sanchopanza hook`.
- **MCP client** (Cursor, Codex, Copilot, anything): `build_server(squire).run()`.
- **Anything else**: `await guardian.before_tool(ToolCall(name, args))` returns allow, deny
  with a reason, or rewrite with new arguments. Map those three to your harness.

## 4. Respect the four invariants, or do not bother

**Fail open.** No provider, no key, exhausted budget, provider bug: every policy returns the
default the harness had before. `Squire.decide` never raises. If you wrap it in something
that can raise, you have broken the main safety property.

**Asymmetry.** The direction whose error the user sees needs more confidence than the cheap
direction. Downgrade a model at 0.75, upgrade at 0.60. Drop a page only on explicit low
relevance; in doubt it enters. Emit a citation verdict at 0.80, else abstain. The guard can
deny, never approve.

**Trace.** One journal event per decision, with probabilities, confidence, cost, latency and
the outcome. It is the audit trail, and later it is the labelled dataset you tune on.

**Cache-safe.** Act only where acting cannot invalidate a cached prompt prefix. The prefix
renders as `tools -> system -> messages` and a change at any level invalidates that level and
everything after it, so:

| Safe to act | Never |
|---|---|
| Before the first request of a session | Rewriting `tools` mid-session |
| On content about to be appended (a page, a search result, a subagent's prompt) | Editing the system prompt mid-session |
| Inside a tool the model called anyway | Deleting or rewriting earlier turns |
| On a delegation, choosing the subagent's model | Switching the model of a running conversation |
| As an appended note (`additionalContext`) | |

If a harness genuinely needs the tool set to change mid-session, use the channels that append
rather than swap: tool search, or `tool_addition` / `tool_removal` blocks with
`defer_loading`. Verify it worked by watching `cache_read_input_tokens`: a zero across
repeated requests means something is rewriting the prefix.

**And a fifth thing that is not an invariant but will cost you more than all of them.**
The squire chooses among the options you tell it exist. If one of those options is not
actually deployed, it will route work into the hole confidently, nothing will fail, and
fail-open will never fire. `cheap_search_available` must be a probe that answers "does this
engine exist and answer, right now", never a constant and never a quota check. In production
that mistake produced a report beginning "this research could not be carried out", 75 %
cheaper than delivering one.

## 5. Write the question properly

This is where most of the accuracy lives.

- **Ask it to read, not to predict.** "Is this query written as keywords or as a question?"
  scored 94 %. The earlier version, "would a common search engine find this?", scored 38 %.
  Same decision, same model.
- **Minimal state, named keys.** Send the fields the decision needs and nothing else.
  Irrelevant context degrades the answer. Trim long fields.
- **One dimension per question**, several questions per call. They are answered in parallel
  and cost one round trip.
- **Criteria with examples**, for the true and the false side both. The examples do about
  half the work.
- **Score levels as situations**, not grades. "Look up a fact in a named source and copy it",
  not "easy".
- **Always offer `other` or `none`** when the list may not be exhaustive. The model cannot
  abstain out of domain if you do not let it.
- **Instructions in English, content in any language.** Measured: Spanish content with
  English instructions matched or beat Spanish instructions.

## 6. Long documents: the trap

Triage sees an excerpt, not the whole page. Cutting from the head is wrong on a long
document, because the part that answers the purpose is usually in the middle, and the
decider then judges on a preamble that genuinely does not mention it.

`sanchopanza.text.excerpt` handles this: head plus the window that best matches the purpose
words. It was added after the end-to-end benchmark caught triage dropping the one document
that held the answer, costing twice as much for no answer at all. If you write your own
state builder for a long document, do the same thing, or chunk before you triage.

## 7. Thresholds move only with evidence

The defaults in `Thresholds` were fixed before the runs that measured them and have not been
tuned on those results. Move one when you have 50 cases for that point, a second annotator,
and a confidence-band table that justifies the move. Not before.

Calibration is per primitive, so do not use one global confidence: Truth answers are
under-confident (they are better than they say), Choice answers are well calibrated, and
Score answers are the least reliable, which is why the Score-driven point is gated hardest.

## 8. Measure before you trust

```
sanchopanza bench benches/*.jsonl --provider recorded --fixture fixtures/public-benches.jsonl
sanchopanza bench mycases.jsonl --provider jev --record fixtures/mine.jsonl --out results/today
```

Reports agreement when deciding, coverage, Wilson intervals, AUC, Brier, expected calibration
error, agreement by confidence band and calibration by primitive. Write your own cases in the
same format; real material beats invented material and hard negatives beat easy ones.

For an end-to-end question, "does my agent get cheaper or worse", copy `benchmarks/ab/`:
same tasks, same prompts, one arm with the squire and one without, paired bootstrap over the
pairs. Decision-level accuracy does not answer that question and should not be quoted as if
it did.
