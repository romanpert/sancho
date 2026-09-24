# Changelog

## 0.2.0 (2026-09-24)

Eight new decision points, the first measurement of *where* a decision may be applied, a
defect in this package's own thresholds found by attacking its own thesis, and the smallest
contract change that admits an image.

### Fixed, and the most important line in this release

- **Two gates on one number were one gate at the stricter value.** For a Truth answer from
  this model class, `confidence` is exactly `|2p - 1|`: 651 recorded answers across three
  independent runs, zero deviation. So a policy asking for both `p >= a` and
  `confidence >= c` was asking for `p >= max(a, (1 + c) / 2)`, and the threshold named in the
  configuration was not the one in force. `memory_write` was configured at 0.70 and enforcing
  0.80; source redundancy at 0.80 and enforcing 0.875; the recall and extraction gates had a
  dead clause. The redundant gates are gone, **no threshold value changed**, and the gap
  between the shipped policy and a plain 0.5 cut fell from eight decisions to three
  (78/88 to 85/88, AUC 1.00 throughout). `tests/test_policy.py` pins the identity as a canary.
- **The default model is pinned, not an alias.** `jev-1.13.0` rather than `jev-latest`, which
  is what the vendor's own model page asks for when thresholds have been tuned, and this
  package is nothing but tuned thresholds. The squire also warns once if two model versions
  answer within one session.
- **A provenance criterion written into free-text prose did not work, and the answer was
  already in the decision.** `triage.decide` takes `allowed_kinds` / `denied_kinds` and
  filters on the source kind in code, with no extra call. Found by the steerability bench.


### Added

- **Agent memory** (`points/memory.py`): `Squire.remember` (is this fact worth storing),
  `Squire.reconcile` (does it contradict, duplicate or complement a stored one) and
  `Squire.needs_recall` (does this turn need a lookup at all). Recency is never asked of the
  decider: the harness's timestamps decide it in code, because dates are the model class's
  declared weakness, and a collision with unknown recency is flagged, not resolved.
- **Knowledge-graph construction** (`points/graph.py`): `Squire.gate_extraction` (is this
  chunk worth a generative extraction call) and `Squire.verify_edge` (does the text state
  this triple, in this direction). Both mentions are matched in code before any call.
- **Source redundancy** (`points/triage.py`): `Squire.triage_redundant`, for the fetch-heavy
  workloads the end-to-end A/B could not exercise at 1.8 fetches per task.
- **The loop guard** (`points/loop.py`): `Squire.check_loop`, which advises when the goal
  already looks met or a pending check repeats one already run. It appends a note; it never
  denies. It exists because redundant verification is the largest measured waste in an agent
  loop: 18x the clean-run cost, 2.5x the tool calls, no gain in success (arXiv:2608.01347).
- **124 labelled cases** across `benches/{memory,graph-build,retrieval,loop}.jsonl`, a
  recorded run in `fixtures/new-points.jsonl`, results in
  `docs/results/2026-09-24-new-points/`, and `tests/test_new_point_benches.py`, which replays
  them for free in CI.
- **`benchmarks/cache/`**: four arms measuring what narrowing a tool catalog costs when it is
  done once, on alternate turns, or afresh every turn.
- **`docs/where-it-pays.md`**: which decisions are worth taking at all. Three economies
  (substitution, avoidance, affordability), one anti-economy (the prompt cache), a catalog of
  levers ranked by how sure we are, and four things not to use a decision model for.
- **Steerability bench** (`benches/steerability.jsonl`, 14 flipped pairs): the same
  document and topic with only the criterion changed, scored by pair accuracy, because a
  scorer whose inputs are only (query, document) scores 0 % there by construction. 11 of 14.
  Written to check a marketing claim that turned out to be false: instruction-following
  rerankers exist, are cheaper than this model, and four public benchmarks measure them.
  `docs/results/2026-09-24-steerability/`.
- **Attachments** (`sanchopanza.media`): `state` may carry an `Attachment` at any depth, and
  the questions do not change. No vendor sells a calibrated non-generative multimodal
  decision model today - across seven image-classifier vendors not one publishes an ECE - but
  the shape is proven by an independent paper, and a local vision model behind `LocalDecider`
  works now. A text-only provider **refuses** an attachment rather than dropping it.
- **`Thresholds.audit`**: a pre-registered, reproducible sample of decisions marked in the
  journal for re-labelling, so a threshold can never be tuned on cases picked afterwards.
- A warning when the tool selection changes within a session, which is the 4.15x mistake.
- `Thresholds.remember`.

### Changed

- **A fourth invariant: cache-safe by construction.** A decision acts only where acting
  cannot invalidate a cached prefix. Measured over 8 turns on claude-sonnet-5: narrowing a
  58-tool catalog once is **43 % cheaper**; narrowing it on alternate turns is **14 % dearer**
  than never narrowing; narrowing it afresh every turn reads **zero** tokens from cache and
  costs **4.15x** the arm that decided once. Same decision, different moment, opposite sign.
- `HarnessConfig.cheap_search_available` is documented as a **probe, not a flag**, and the
  README example no longer shows `lambda: True`. A capability that is declared rather than
  probed routes work into a hole while fail-open never fires: in production that produced a
  report beginning "this research could not be carried out", 75 % cheaper than delivering.
- `docs/savings.md` now states the comparison that applies inside a warm loop. A cached read
  costs 0.1x base input, so for tokens already in a prefix the multiple is 4.8x on a
  Sonnet-class model, not 48x. Which column applies depends on whether the decision replaces
  a call or avoids tokens.
- The bench runner scores the new points, and computes AUC for gates whose label is a word
  rather than a boolean.
- `docs/paper.md` is draft 3: Sections 5.10 and 5.11, a rewritten analysis, four new threats
  to validity and twelve items of future work.

### Known limitations, measured

- **Three decisions still separate the policy from a plain 0.5 cut** (85 of 88 against 86 of
  88, AUC 1.00 throughout) after the redundant-gate fix above. Those are not tuned away: the
  rule is 50 cases and a second annotator per point, and this bench has 12 to 20 and one.
- **The steerability bench has no baseline.** An instruction-following reranker over the same
  pairs is the comparison that matters and it has not been run, so that bench says what this
  layer does, not what it does better.
- **The `duplicate` branch of `reconcile` never fired** on 16 cases. In practice the point is
  a contradiction detector with a safe default.
- **One confident error on the edge check**: a true triple rejected at confidence 1.00, where
  the text said "declares unconstitutional" and the triple said "annuls". It is why that
  point is specified as a filter in front of a human, not as an autonomous committer.

### Also in 0.2.0: work landed since 0.1.0 and not previously released

#### Fixed

- **Triage judged a long document on its first 1,500 characters.** On a 10,000-character page
  the part that answers the purpose is usually in the middle, so the decider was reading a
  preamble that genuinely did not mention it and dropping the page. `sanchopanza.text.excerpt`
  now sends the head plus the window that best matches the purpose words, deterministically and
  with no extra tokens. Documents at or under the limit are returned unchanged, so no bench
  number moved and the recorded replay still matches byte for byte.
  Found by the new end-to-end A/B, where it made a run cost twice as much and return nothing.

#### Added

- `benchmarks/ab/`: the end-to-end A/B. Same agent, same tasks, one arm with the squire and
  one without, over a fixed corpus built from files already in this repository. Paired
  bootstrap over (task, repetition) pairs, ground truth pinned to a string unique to one
  document, two retrieval conditions and two document sizes, with a spend cap.
- `docs/savings.md`: what the layer costs and the break-even arithmetic, with exact token
  counts and no invented saving percentage.
- `docs/governance.md`: branch protection, the PyPI environment (including the tag rule the
  release workflow needs) and how to release.
- `skills/sanchopanza/SKILL.md`: a skill for coding agents wiring this into a harness.
- `.github/CODEOWNERS`, a release workflow with trusted publishing, a logo and a README.

#### Changed

- Decision point `tools`: which groups of a tool catalog a request needs (one Truth per group,
  chunked and merged; `Thresholds.tools`, in doubt keep; `always` pinned by code; never empty).
  Motivated by harnesses that bind every schema on every step. Not yet measured on a public bench.
- `Squire.select_tools`.
- Harness adapter `sanchopanza.harness.langchain.ToolSelectMiddleware` for LangChain / LangGraph /
  deepagents `AgentMiddleware` (`wrap_model_call` and async), tested in shape.
- Extra `langchain`.

## 0.1.0 (2026-09-21)

First public release, extracted from the decision layer of a production research agent.
Distributed as `sanchopanza` under Apache 2.0; `import sanchopanza`, command `sanchopanza`
with `sancho` as a short alias.

- Contract: Choice / Score / Truth questions, calibrated Answers, Decider protocol.
- Ten decision points with measured question texts and pure policies: routing, search, triage (with injection), citation, plan lines and dependencies (with DAG cleanup), report review, shell guard, entity alignment, fact relation, closed-vocabulary classification (with other).
- Squire: fail-open, per-job budget, journal event per decision.
- Providers: TypeSafe Jev (HTTP, no SDK), recorded / recording, null, LLM forced to schema (Anthropic and OpenAI completers), local handlers, fallback and per-point routing.
- Harness adapters: Claude Agent SDK hooks, Claude Code command hook, MCP server, OpenAI-Agents-style guardrail, harness-agnostic Guardian.
- Eval: bench runner, statistics in plain Python, calibration by primitive.
- Public benches (pseudonymized) and the working paper.
