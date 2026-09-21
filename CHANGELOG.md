# Changelog

## Unreleased

- Decision point `tools`: which groups of a tool catalog a request needs (one Truth per group,
  chunked and merged; `Thresholds.tools`, in doubt keep; `always` pinned by code; never empty).
  Motivated by harnesses that bind every schema on every step. Not yet measured on a public bench.
- `Squire.select_tools`.
- Harness adapter `sancho.harness.langchain.ToolSelectMiddleware` for LangChain / LangGraph /
  deepagents `AgentMiddleware` (`wrap_model_call` and async), tested in shape.
- Extra `langchain`.

## 0.1.0 (2026-09-21)

First public release, extracted from the decision layer of a production research agent.

- Contract: Choice / Score / Truth questions, calibrated Answers, Decider protocol.
- Ten decision points with measured question texts and pure policies: routing, search, triage (with injection), citation, plan lines and dependencies (with DAG cleanup), report review, shell guard, entity alignment, fact relation, closed-vocabulary classification (with other).
- Squire: fail-open, per-job budget, journal event per decision.
- Providers: TypeSafe Jev (HTTP, no SDK), recorded / recording, null, LLM forced to schema (Anthropic and OpenAI completers), local handlers, fallback and per-point routing.
- Harness adapters: Claude Agent SDK hooks, Claude Code command hook, MCP server, OpenAI-Agents-style guardrail, harness-agnostic Guardian.
- Eval: bench runner, statistics in plain Python, calibration by primitive.
- Public benches (pseudonymized) and the working paper.
