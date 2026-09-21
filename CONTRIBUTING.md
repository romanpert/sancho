# Contributing

Three kinds of contribution are worth the most, in this order.

1. **Cases with labels.** A decision point with 50 cases and two annotators is worth more
   than a new feature. Format in `docs/benches.md`. Real material, hard negatives, no
   identifiable private individuals. If you also run them (`sancho bench ... --record`),
   send the fixture and the `summary.md`.
2. **A provider.** One file in `src/sancho/providers/`, implementing `Decider`, with a
   docstring that states how its confidence is computed and a test that exercises it with a
   fake transport. Register it in `pyproject.toml` under `sancho.providers`.
3. **A tested harness adapter.** One file in `src/sancho/harness/`, a translation of
   `Guardian` verdicts to the harness's wire format, with tests on the shapes and a
   docstring that says what was run against the real harness and what was not.

Rules of the house:

- No test calls a paid API. Record a fixture with `RecordingDecider` and replay it.
- Policies are pure functions. If a policy needs I/O, it is not a policy.
- Code before model. If a deterministic check can decide, it goes first and the model is
  not called.
- A threshold changes only with a bench of 50 cases per point, a second annotator, and the
  confidence-band table in the pull request.
- `ruff check` and `ruff format` clean; `pytest` green; the CI replays the public benches.
- Plain language in docstrings. Say what was measured and what was not.

Run locally:

```
uv venv && uv pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests && pytest -q
sancho bench benches/*.jsonl --provider recorded --fixture fixtures/public-benches.jsonl
```
