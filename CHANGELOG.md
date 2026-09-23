# Changelog

## Unreleased

### Fixed

- **Triage judged a long document on its first 1,500 characters.** On a 10,000-character page
  the part that answers the purpose is usually in the middle, so the decider was reading a
  preamble that genuinely did not mention it and dropping the page. `sanchopanza.text.excerpt`
  now sends the head plus the window that best matches the purpose words, deterministically and
  with no extra tokens. Documents at or under the limit are returned unchanged, so no bench
  number moved and the recorded replay still matches byte for byte.
  Found by the new end-to-end A/B, where it made a run cost twice as much and return nothing.

### Added

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

### Changed

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
