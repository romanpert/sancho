# Benches

Three JSON-lines files, one labelled case per line, comments with `#`. Content is Spanish;
keys and labels are English.

| File | Cases | Points | Labels |
|---|---|---|---|
| `benches/core.jsonl` | 74 | routing 20, search 18, triage 16, citation 20 | one annotator |
| `benches/safety.jsonl` | 106 | injection 28, command 32, unsourced 22, numeric_citation 24 | one annotator; adversarial cases written, not harvested |
| `benches/graph.jsonl` | 65 | entity 24, facts 20, dependency 20, plan 1 (56 pairs) | one annotator |
| `benches/memory.jsonl` | 46 | memory_write 16, memory_collision 16, recall 14 | one annotator, 2026-09-24 |
| `benches/graph-build.jsonl` | 36 | extract_gate 16, edge 20 | one annotator, 2026-09-24 |
| `benches/retrieval.jsonl` | 16 | redundant_page 16 | one annotator, 2026-09-24 |
| `benches/loop.jsonl` | 26 | goal_met 14, repeats_check 12 | one annotator, 2026-09-24 |

The four files added in 0.2.0 replay from `fixtures/new-points.jsonl` and are weaker evidence
than the first three: fewer cases per point, one sitting, and three labels corrected after
seeing the run (the corrections and their reasons are in the file headers). Read
`docs/results/2026-09-24-new-points/summary.md` with `docs/paper.md` Section 5.10, which
reports what those runs found about this package's own thresholds.

The 298 closed-vocabulary classifications reported in the paper are not published: they are
the register of a real investigation.

## Format

```json
{"id": "rt-01", "point": "routing", "input": {"task": "...", "brief": "..."}, "expected": "light"}
```

| Point | Input keys | Expected |
|---|---|---|
| routing | task, brief | light / default / deep |
| search | query, previous, brief | cut / cheap / full |
| triage | purpose, title, url, text | keep / drop |
| citation, numeric_citation | claim, section | supported / contradicted / unsupported |
| injection | purpose, text | true / false |
| command | command | true / false |
| unsourced | task, result | true / false |
| entity | a, context_a, b, context_b | true / false |
| facts | fact_a, fact_b | agree / conflict / unrelated |
| dependency | a_title, a_goal, b_title, b_goal | true / false |
| plan | lines [{id, title, goal}], edges [[a, b], ...] | evaluated as a whole |
| classify | field, text, options, context | one option name |

## Running

```
sanchopanza bench benches/*.jsonl --provider recorded --fixture fixtures/public-benches.jsonl
sanchopanza bench benches/*.jsonl --provider jev --record fixtures/mine.jsonl --out results/today
```

The runner sends each case through the same `Squire` methods production uses, with
`allow_upgrade=True` so all three routing tiers are reachable, and reports agreement when
deciding, coverage, Wilson 95 % intervals, median latency, AUC / Brier / ECE for binary
points, agreement by confidence band, calibration by primitive, and for `plan` the raw and
cleaned precision / recall with the parallel waves against the reference.

`results.json` holds one row per case with the raw probability, so everything is
recomputable with `sanchopanza.eval.stats`.

## The rule

A threshold moves when a point has 50 cases, two annotators with reported agreement, and the
band table justifies the move. Until then the thresholds in `Thresholds` are the ones fixed
before the September 2026 runs.

## Contributing cases

Real material beats written material; hard negatives beat easy ones; a second annotator
beats a bigger bench. Do not include identifiable private individuals. Keep the content
language: the point of these benches is that the instructions are in English and the
content is not.
