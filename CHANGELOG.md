# Changelog

## 0.2.0 (2026-09-24)

Eight new decision points, the first measurement of *where* a decision may be applied, and
one negative result about this package's own thresholds that is reported rather than fixed.

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

- **The shipped thresholds are too strict for the new points.** Across the six binary points
  the evaluator is right 86 of 88 at a plain 0.5 cut and 78 of 88 under the thresholds this
  package ships, with AUC 1.00 on every one. All eight lost decisions are refusals to act, so
  the layer is safe as shipped and leaving value unclaimed. They were **not** tuned: the rule
  is 50 cases and a second annotator per point, and this bench has 12 to 20 and one.
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
