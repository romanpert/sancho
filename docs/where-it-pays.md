# Where a decision layer pays, where it does not, and how to tell before you build it

`docs/savings.md` answers "what does one decision cost". This document answers the harder
question: **which decisions are worth taking at all**, and why our own end-to-end A/B found
nothing when the arithmetic said it should have found something.

The short version, and everything below is the argument for it:

> A cheap calibrated decision pays reliably when it **replaces a call to a bigger model that
> was going to happen anyway**. It pays unreliably when it tries to **keep tokens out of a
> big model's context**, because that saving depends on the shape of the workload and is
> mostly cache-priced. It pays in a third way that is not a saving at all: it makes quality
> checks cheap enough to run always instead of never. And it can **cost** money, badly, if it
> is wired to a point where acting mutates a cached prefix.

Every figure marked **[M]** is measured in this repository and reproducible from it.
**[P]** is a primary published source with a URL. **[D]** is derived arithmetic from those.
Nothing here is an estimate presented as a measurement.

---

## 1. The three economies, and the anti-economy

### Substitution: the decision replaces an LLM call

Somewhere in the pipeline a model is already being asked a yes/no or a pick-one: is this
citation supported, are these two mentions the same company, does this chunk contain an
entity, is this comment worth showing, does this fact contradict the stored one. The answer
is consumed by code, and nothing about it has to be written as prose.

The saving is a price ratio, it is bounded below by that ratio, and it does not depend on
the workload's shape. This is the only economy where the arithmetic is safe.

| Replacing | Price of the thing replaced | Ratio to 29 millionths a decision |
|---|---|---|
| Claude Opus 5, input only | 5.00 USD/MTok **[P]** | 119x **[D]** |
| Claude Sonnet 5, input only | 2.00 USD/MTok **[P]** | 48x **[D]** |
| Claude Haiku 4.5, tool-forced, same 156 cases | 0.2337 against 0.0048 USD **[M]** | **49x, and 3x faster** |
| Bedrock Guardrails content filter, ~0.60 USD/MTok | 0.15 USD per 1k text units **[P]** | 14x **[D]** |
| Azure AI evaluations meter / Vertex legacy model-based metrics | 20 USD/MTok in + 60 out **[P]** | **~1,450x per 1,000 judgments** **[D]** |

That last row is not a typo and it is the most under-appreciated number in this document.
At 1,500 input and 200 output tokens per judgment, a hosted evaluation meter bills about
42 USD per thousand judgments; the same thousand judgments here cost 0.029 USD. The judge
model is not where the money goes. The meter is.

### Avoidance: the decision keeps tokens out of the big model

Page triage, redundancy, context pruning. The saving is `dropped tokens x price`, and there
are three reasons it disappoints:

1. **It is priced at the cache-read rate, not the list rate.** A page that enters the context
   is paid once at full price and then, on every later turn, at 0.1x **[P]**. So the honest
   competitor to a 0.042 USD/MTok decider inside a warm loop is 0.20 USD/MTok on Sonnet 5 and
   0.50 on Opus 5: the multiple is 4.8x and 11.9x **[D]**, not 48x and 119x.
2. **Fewer input tokens is not proportionally fewer dollars.** AgentDiet cut input tokens by
   39.9-59.7 % and total cost by only 21.1-35.9 % at equal performance **[P]**. That gap is
   the honest ceiling for any context-pruning classifier.
3. **It needs the workload to be fetch-heavy and the fetches to be mostly useless.** Ours
   was not, and we measured that rather than assuming it.

### Affordability: the decision makes a quality check cheap enough to always run

This is the one we did not see coming, and it is the reason the null A/B did not kill the
project. Some checks are not skipped because they are hard; they are skipped because running
them on everything is unaffordable. Verify every extracted triple. Verify every citation.
Resolve every candidate entity pair after blocking. Test every retrieved chunk for relevance
rather than trusting the top-k.

LazyGraphRAG makes the point by construction: its relevance-test budget is the single
parameter that controls the whole cost/quality curve, evaluated at 100, 500 and 1,500 binary
judgments **per query** **[P]**. At 29 millionths a judgment, 1,500 of them cost 0.043 USD.
The lever stops being "how do we afford more checks" and becomes "how many do we want".

The output here is not a smaller bill. It is a check that used to be sampled and can now be
exhaustive. Report it as quality, not as savings, or you are lying with a true number.

### The anti-economy: acting where acting invalidates a cache

The prefix hierarchy is `tools -> system -> messages`, and a change at any level invalidates
that level and everything after it **[P]**. So a decision that rewrites the tool array, edits
the system prompt or rewrites history does not merely fail to save: it converts every cached
read in the rest of that turn into a fresh write at 1.25x.

We measured it (`benchmarks/cache/`, 8 turns, claude-sonnet-5, 4 isolated arms) **[M]**:

| Arm | Cached reads | Cache writes | Cost | vs deciding once |
|---|---|---|---|---|
| full catalog, fixed | 201,957 | 28,851 | 0.13873 USD | 1.75x |
| narrowed once, then fixed | 98,567 | 14,081 | **0.07916 USD** | 1.00x |
| narrowed, alternating two stable subsets | 129,312 | 43,104 | 0.15770 USD | 1.99x |
| a different subset every turn | **0** | 117,148 | 0.32864 USD | **4.15x** |

Narrowing the catalog **once** is worth 43 %. Narrowing it on alternate turns costs 14 %
*more* than never narrowing. Narrowing it differently every turn reads **nothing** from cache
across eight turns and costs 4.15x the arm that took the same decision once. Same decision,
same tools, different moment, opposite sign.

---

## 2. The rule that generalises all of it: *when* beats *how good*

The clearest evidence for this is not ours. Meta deployed Infer in batch, assigning 20-30
issues to developers: the fix rate was near zero. They switched the same analysis, with the
same false-positive rate, to run at diff time: the fix rate went **over 70 %** **[P]**.

> "The same program analysis, with same false positive rate, had much greater impact when
> deployed at diff time." - Distefano, Fahndrich, Logozzo, O'Hearn, CACM 62(8), 2019.

A decision layer is subject to the same law, in both directions. Our cache result is the cost
side of it: the same selection is worth -43 % or +315 % depending on which turn it lands on.
Meta's is the value side: the same finding is worth nothing or everything depending on when
it is shown. **Choose the attachment point before you tune the model.**

Three corollaries the package now follows:

- **Decide where there is no prefix to invalidate.** Before the first request of a session; on
  content that is about to be appended (a fetched page, a subagent's prompt); inside a tool
  the agent called anyway. Never by rewriting `tools`, `system` or history mid-session.
- **Routing a subagent is cache-safe; routing the main loop is not.** A subagent does not read
  the parent's cache in any case, so choosing its model costs nothing extra; switching the
  model of a running conversation re-reads the whole thing uncached **[P]**.
- **Predict behaviour, not truth, when you have the choice.** Atlassian ran both filters over
  the same pipeline: an encoder classifier predicting *will an engineer act on this* added
  20 points of human alignment, and an LLM-as-judge predicting *is this claim correct* had
  "minimal impact" **[P]**. Meta's result explains why.

---

## 3. What we tried, and what it cost us to learn

Negative results first, because they are the ones that change what you build.

**The end-to-end A/B on page triage was null, twice.** 64 paired runs, two retrieval
conditions, two document sizes: every cost interval spans zero, both latency intervals
exclude it, quality did not move **[M]**, `docs/savings.md`. The reason is visible in the
runs: the agent fetched 1.8 documents per task and triage dropped 0.45 of them. Avoidance
needs many fetches, most of them useless. Ours had neither.

**Making the documents larger did not rescue it.** In that corpus, size and retrieval
difficulty are coupled: bigger documents means fewer of them, each holding more, so the first
one opened usually had the answer **[M]**.

**The A/B still paid for itself, by finding a bug no decision-level bench could.** Triage was
judging a 10,000-character document on its first 1,500 characters, dropping the one page that
held the answer; the agent re-fetched it, hit its turn cap and returned nothing at twice the
cost. `sanchopanza.text.excerpt` now sends the head plus the window matching the purpose. No
bench number moved, because documents that already fit are unchanged **[M]**.

**The first run of the cache benchmark produced a flattering lie.** All arms shared one
catalog, so later arms read caches earlier arms had written, and the naive per-turn wiring
came out cheapest of the three. The fix is a per-arm tag in every tool description, plus a
`churn` arm, because the first run taught us the risk is not narrowing but *instability*
(`benchmarks/cache/results/summary.md`) **[M]**.

**The threshold written in the configuration was not the one in force.** On the 124 new
cases the six binary points got **86 of 88** at a plain 0.5 cut and **78 of 88** under the
shipped policy, with **AUC 1.00 on all six** **[M]**. That looked like conservatism. It was a
defect.

For a Truth answer from this model class, `confidence` is exactly `|2p - 1|` - verified on
651 recorded answers across three independent runs, with zero deviation **[M]**. Probability
and confidence are the same number. So a policy asking for both `p >= 0.70` and
`confidence >= 0.60` is asking for `p >= 0.80`, and `memory_write`, configured at 0.70, was
enforcing 0.80 and rejecting facts that scored 0.75 and 0.76. **Two gates on one number is
one gate at the stricter value.**

Removing the redundant gates moved **no threshold value** and closed the gap to three
decisions: **85 of 88** **[M]**. A confidence gate still earns its place where it is the only
gate and the point wants an abstention band - the citation verdict, the entity band, the edge
check - and nowhere else.

The lesson generalises past this package: **check whether your two signals are one signal**
before concluding that a model is under-confident. What remains true is that thresholds
should be derived rather than picked, and Google's deployed equivalent shows how - a
probability threshold chosen per language to hit a *target precision*, reported as recall@X,
lowered from 70 % to 50 % and then to 40 % once a human preview step existed **[P]**.

**And a bench where the model corrected the annotator.** Three of our labels were wrong on
the question's own criteria, and the disagreement found them. They are relabelled with the
reason recorded in the bench header, and both the before and after numbers are published.
Two others were left alone: the model missed them at low confidence, and a bench that moves
its labels to match the model measures nothing.

---

## 4. The catalog: every lever we can argue about, ranked by how sure we are

Ranking is by *confidence that the saving is real*, not by size. "In the package" means it is
implemented with a bench; "designed" means the arithmetic is here and the code is not.

### Tier 1 - substitution, measured, safe to quote

| Lever | Replaces | Calls scale with | Status | Evidence |
|---|---|---|---|---|
| **Citation verification** | the big model re-reading each cited source | citations per report | in the package | 19/20, 23/24 with numbers, 100 % when it emits a verdict **[M]** |
| **Entity resolution after blocking** | an LLM judging each candidate pair | **pairs**, i.e. quadratically before blocking | in the package | 24/24, AUC 1.00 on hard pairs **[M]**; blocking leaves 386M pairs for 132 true matches in one published corpus **[P]** |
| **Triple verification before commit** | an LLM re-reading the chunk per proposed edge | triples extracted | in the package | 8 edges committed, **0 wrong**, 3 to review on 20 cases **[M]**; a LoRA-tuned 7B judge beats no judge by 5 points of F1 in GraphJudger **[P]** |
| **Injection screening on fetched content** | a hosted guardrail at ~0.60 USD/MTok | pages fetched | in the package | 28/28, AUC 1.00, against a regex at 23/28 **[M]** |
| **Closed-vocabulary classification** | a small LLM doing extraction-by-prompt | records | in the package | 80-85 % against independent labels, majority baseline 43-62 % **[M]** |
| **Extraction gating before a generative pass** | the generative extractor, on chunks with nothing in them | chunks in the corpus | in the package | 15/16, AUC 1.00 **[M]**; LazyGraphRAG makes this budget the whole cost curve **[P]** |

### Tier 2 - substitution, argued, not yet measured end to end

| Lever | Replaces | Calls scale with | Status | The number that motivates it |
|---|---|---|---|---|
| **The loop guard** (goal met, repeated check) | nothing today; the agent simply keeps going | turns | in the package | redundant verification at its extreme cost **18x** the clean-run median, 2.5x the tool calls, 3x the wall time, **no success improvement**, preregistered over 4,644 runs **[P]**. Ours: 14/14 and 12/12, AUC 1.00 **[M]** |
| **Memory write gate** | the extraction call a memory pipeline makes on every turn | turns | in the package | Mem0 runs extraction unconditionally per message pair; nobody gates it **[P]**. Ours: 16/16 at 0.5, 12/16 under shipped thresholds **[M]** |
| **Memory collision** (contradicts / adds nothing) | the ADD/UPDATE/DELETE/NOOP call, 1 of 2 LLM calls per message pair in Mem0 **[P]** | candidate facts x similar stored facts | in the package | 14/16 **[M]**. `replace` fired 4/4 correctly; **`duplicate` never fired** at shipped thresholds, which is a limitation, not a feature |
| **Recall gating** | a memory lookup per turn; Anthropic's memory tool prompt is literally "always view your memory directory before doing anything else" **[P]** | turns | in the package | 14/14, AUC 1.00, ECE 0.051 **[M]** |
| **Model per subtask** | nothing; it changes which model runs | delegations | in the package | 17/20 raw, 11/11 above 0.75 confidence, against a small LLM at 8/20 **[M]**. Cache-safe **only** because it routes subagents |

### Tier 3 - avoidance, workload-dependent, prove it on your own traffic

| Lever | Why it is here and not in tier 1 |
|---|---|
| **Page triage** | Measured accurate (14/16) and measured *null* end to end on our workload **[M]**. Break-even is 60 tokens a page on a Sonnet-class orchestrator **[D]**, which every real page clears; whether the tokens would have changed the deliverable is the part we could not show. |
| **Redundancy between sources** | The lever our A/B could not exercise at 1.8 fetches per task. AUC 1.00, 15/16 at a 0.5 cut, 11/16 under shipped thresholds **[M]**. The experiment that would settle it is in section 6. |
| **Search tier routing** | 17/18 **[M]**, and the saving is whatever your search provider charges, which we cannot measure for you. **Read the warning in section 5 before wiring it.** |

### Tier 4 - do not use a decision model for this

| Not this | Because |
|---|---|
| **Tool selection, per turn, by rewriting `tools`** | Measured at 1.99x to 4.15x the cost of deciding once **[M]**. Decide once per session, or use the channels that append instead of swapping. |
| **Tool selection at all, in a harness that has tool search** | Anthropic's tool search is server-side, cache-safe (schemas are appended, not swapped) and reports 85 % fewer definition tokens, 77k to 8.7k, with accuracy *up* **[P]**. Competing with it is a losing trade. |
| **Deduplicating fetches by URL** | A dict does it. A published multi-agent run reports a 92.4 % per-case cache hit rate from a plain URL-keyed cache **[P]**. Keep the model for semantic redundancy, which a dict cannot see. |
| **Reranking retrieved documents** | A dedicated reranker is better and cheaper, and it is steerable too. See the section below: this one is worth spelling out, because the opposite is being marketed. |
| **Anything arithmetic, or any comparison of dates** | The model class reads numbers and dates as text, and its own card says so. Our memory collision point never asks which fact is newer; the harness's timestamps answer that in code. |
| **Being the only barrier before an action** | The decider is itself vulnerable to instructions injected into its state. It adds denials; it never grants permission. |

---

## 4b. Reranking: the pitch we were being handed, and why we are not taking it

A vendor's post frames the top-100-to-top-5 step as a choice between a cross-encoder that
"cannot be steered", an LLM reranker at "27x cost", and a decision model that is "steerable
and cheap". It flatters us, so we checked it.

**"Cross-encoders cannot be steered" is false in 2026.** Instruction-following is a shipped,
priced feature: Voyage sells `rerank-2.5` and `rerank-2.5-lite` as instruction-following,
with the instruction appended to the query in natural language, and their own worked example
is our pitch nearly word for word ("retrieve regulatory documents and legal statutes, not
court cases") **[P]**. ZeroEntropy's `zerank-2` takes instructions and business context.
Contextual AI shipped one in March 2025 for recency, document type and source priority. Four
benchmarks exist to measure the capability: MAIR, IFIR, FollowIR, InstructIR.

**The price argument inverts.** Verified on vendor pages, 2026-09-24: Voyage
`rerank-2.5-lite` at 0.02 USD/MTok and ZeroEntropy `zerank-2` at 0.025 are **below** our
0.042, and a self-hosted Qwen3-Reranker is lower still **[P]**. The "27x" in the post
compares an LLM reranker against a reranker, and then recommends the option that costs about
twice the steerable cross-encoder.

**Someone published our differentiation first, cheaper.** ZeroEntropy's "zerank-2 as a
calibrated classifier" (2026-04-02) argues the score is an absolute probability, gives
thresholds, and replaces top-K with a threshold: 85 % context compression at 90 % recall on
150-page clinical documents **[P]**. That is the calibrated-gate story, owned by a reranker
vendor at 60 % of our price.

**And pointwise scoring is the known-worst architecture for ranking.** Aggregate quality runs
pointwise LLM below cross-encoder below listwise, and N documents means N calls against one
listwise pass at about 300 ms for a top-100 **[P]**.

So: **we do not compete on reranking.** What survives is narrower and worth stating exactly.
Our difference is not one calibrated score per document; it is **several independent typed
questions about one state in a single pass** - is it an official source, does it state a
figure, is it an opinion piece, is it in range - where a reranker takes one blended
instruction or runs once per criterion. The open door in the literature is **exclusion**:
models solve at most one ExcluIR query in eight and negation is where instruction-following
degrades **[P]**.

Our own first measurement of that, deliberately small: 14 flipped pairs where only the
criterion changes, **11 of 14 both sides right**, with five exclusion criteria of which four
passed **[M]** (`docs/results/2026-09-24-steerability/`). No baseline was run, so it says
what we do and not what we do better. The three-arm experiment that would settle it is at the
end of that file.

One thing that measurement did change immediately: a provenance criterion written into the
purpose prose failed while the answer sat unused in the same decision (`source_kind`:
`news`, confidence 1.00). `triage.decide` now takes `allowed_kinds` / `denied_kinds` and
filters in code. **A criterion that a Choice question already answers does not belong in
free-text prose.**

## 5. Two ways to lose money with a layer that "fails open"

Fail-open protects you from the decider being unavailable. It does not protect you from these.

**The alternative that does not exist.** A routing policy chooses between options the harness
claims to offer. If one of them is not actually deployed, the policy will route work into a
hole, confidently and cheaply, and the fail-open invariant will never fire because nothing
failed. We have seen this in production: a search router asked whether a cheap engine was
"available", was handed a function that answered *is there quota left* rather than *does this
service exist*, routed every query to a stub and produced a report beginning "this research
could not be carried out". The arm was 75 % cheaper. The 75 % was the cost of not delivering.

The package's own README used to show `cheap_search_available=lambda: True`. It now shows a
probe, because a flag that is always true is the same bug waiting in the example code. **A
capability must be probed, not declared.**

**The gate with nothing to gate.** Below roughly 17 % precision in whatever generates the
candidates, filtering them adds nothing: ByteDance measured an off-the-shelf LLM reviewer at
10.1 % precision and their trained filter moved it to 10.6 % **[P]**. A filter needs a signal
to separate. Measure the thing you are filtering before you build the filter.

---

## 6. The experiments that would move these claims

Each of these is specified enough that a disagreement becomes a measurement.

1. **The fetch-heavy A/B.** A task that gathers 20-40 sources before writing, over a corpus
   where most of what retrieval returns is genuinely off-target, with the redundancy point on
   and off. This is the one that would license or kill a headline saving figure for avoidance.
   Prediction, stated in advance: a real effect on input tokens, a smaller one on cost, and
   latency still worse. Estimated spend at Sonnet 5 prices: 5-10 USD.
2. **Fifty cases and a second annotator per new point**, then thresholds set the way Google
   sets them: per point, to a target precision, reported as recall@X. Prediction: the
   86/88-against-78/88 gap closes to within two decisions without any loss in the safe
   direction.
3. **Deferred labelling in production.** Sample a fraction of *confident* decisions and
   re-label them. AWS's shipped pattern for exactly this is to review everything below
   threshold **and** randomly sample 5 % above it, as a continuing audit of the threshold
   **[P]**. The label must be behavioural (did the harness act, was it reverted), not
   heuristic: heuristic labels cap an actionability classifier at AUC 0.59-0.68, and the label
   definition dominates the model **[P]**.
4. **The memory pipeline, end to end.** Mem0-shaped write path with and without the write gate
   and the collision point, measured on calls, tokens and retrieval quality. Nobody has
   published this: only 2 of 9 memory systems surveyed in 2026 report any efficiency metric at
   all **[P]**.
5. **A within-family control.** Every comparison here is against an LLM of another family. An
   open-weight classifier behind the same contract would separate "non-generative" from "this
   particular vendor".

---

## Sources

Measured **[M]** figures come from this repository: `docs/results/2026-09-21-public/` (the
paper's public run), `docs/results/2026-09-24-new-points/` (the new points),
`benchmarks/ab/results/` (the end-to-end A/B) and `benchmarks/cache/results/` (the cache
arms). All replay or reproduce from the files in the repository.

Published **[P]** sources, all accessed 2026-09-24:

- Anthropic, *Advanced tool use* (2025-11-24). 58 tools ~55k tokens; a 134k peak; tool search
  77k -> 8.7k, 85 %; programmatic tool calling 43,588 -> 27,297 tokens.
  https://www.anthropic.com/engineering/advanced-tool-use
- Anthropic, *Prompt caching* docs. Cache read 0.1x, 5-minute write 1.25x, 1-hour write 2x;
  the `tools -> system -> messages` invalidation hierarchy.
  https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Anthropic, *How we built our multi-agent research system* (2025-06-13). Agents ~4x the
  tokens of chat, multi-agent ~15x; token usage explains 80 % of performance variance.
  https://www.anthropic.com/engineering/multi-agent-research-system
- Weinberger, S., Hozez, A., *Prompt-induced waste in coding agents* (arXiv:2608.01347, 2026).
  Preregistered, 4,644 runs, 24 tasks, 7 models. Redundant verification at level 3+: 18x the
  clean-run median cost, 2.5x tool calls, 3x wall time, no success gain.
- Distefano, D., Fahndrich, M., Logozzo, F., O'Hearn, P., *Scaling static analyses at
  Facebook*, CACM 62(8), 2019. Batch ~0 % fix rate to diff-time >70 %, same analysis, same
  false-positive rate.
- Atlassian, *RovoDev code reviewer: a large-scale online evaluation* (arXiv:2601.01129,
  2026). ModernBERT actionability classifier +20 points of human alignment; an LLM-as-judge
  factual-correctness check had "minimal impact".
- Frommgen, A. et al., *Resolving code review comments with ML*, ICSE-SEIP 2024. Google's
  deployed triage is a probability threshold tuned per language to a target precision,
  reported as recall@X; 7.5 % of all reviewer comments resolved by an ML edit.
- Kang, H., Aw, K. L., Lo, D., *Detecting false alarms from automatic static analysis tools*,
  ICSE 2022 (arXiv:2202.05982). Heuristic-labelled actionability classifiers fall to AUC
  0.59-0.68 once leakage and duplication are removed; the label definition dominates.
- BitsAI-CR (arXiv:2501.15134, FSE 2025). A trained filter moves a 10.14 % generator to
  10.62 % and a 57.03 % generator to 65.59 %: below a precision floor, filtering does nothing.
- *AgentDiet* (arXiv:2509.23586, 2025). Input tokens down 39.9-59.7 %, total cost down only
  21.1-35.9 %, at equal performance.
- Repantis, V. et al., *How many tools should an LLM agent see? A chance-corrected answer*
  (arXiv:2605.24660, 2026). Adaptive depth 93.1 % against 87.1 % at a fixed 5; a fixed K=5
  finds nothing at all on hard queries.
- Microsoft Research, *LazyGraphRAG* (2024-11-25). The relevance-test budget (100 / 500 /
  1,500 binary judgments per query) is the parameter that controls the cost/quality curve.
- Mem0 (arXiv:2504.19413, 2025) and the Anthropic memory tool documentation, for the
  unconditional write path and the ungated retrieval path respectively.
- AWS, Bedrock Guardrails pricing (0.15 USD per 1,000 text units) and the Augmented AI
  condition syntax, including the pattern of reviewing everything below a confidence
  threshold plus a random 5 % above it.
- Azure Retail Prices API, product "Observability": evaluation input 0.02 USD per 1K tokens,
  output 0.06 USD per 1K; Google Vertex legacy model-based metrics at the same effective
  rate. The published Azure pricing page renders these as placeholder dashes.

Two figures that circulate widely and are **not** used here because no primary source was
found: "7 MCP servers = 67k tokens" (and a measured `/context` over-reporting bug of about
3x that inflates much of that literature), and "70-95 % of production agents fail".
