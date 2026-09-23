# Benchmarks

Two different questions live here, and confusing them is the main way people lie with
numbers about decision layers.

| Question | Where | What it answers |
|---|---|---|
| Does the squire decide correctly? | `../benches/` plus `sanchopanza bench` | Decision-level accuracy, calibration, coverage. Replays for free from a recorded fixture. |
| Does the agent get cheaper or worse? | `ab/` | End-to-end cost, latency and answer quality, with and without the squire. Spends real money. |

Decision-level accuracy does not answer the second question and must not be quoted as if it
did. A decision can be right and change nothing about what the job costs.

## The A/B

```
python benchmarks/ab/run.py --verify                       # ground truth check, free
python benchmarks/ab/run.py --repeats 1 --tasks dag        # a pilot, a few cents
python benchmarks/ab/run.py --retrieval noisy --doc-size large --repeats 3
```

Needs `ANTHROPIC_API_KEY` and `TYPESAFE_API_KEY`, and `pip install anthropic`.

**Design.** Eight questions over a corpus of 23 to 56 documents built from files already in
this repository: the paper split by section, the other documents, and the Spanish page texts
of the triage bench. The agent gets two tools, `search` and `fetch(doc_id, purpose)`, and a
deliberately mediocre keyword retriever. Both arms are byte-identical in prompt, tools,
model, thinking and effort. The only difference is that in the `squire` arm `fetch` passes
the page through `Squire.triage_page` first, and a page judged irrelevant to the stated
purpose comes back as a one-line note instead of its text.

**Why a local corpus.** So the run is deterministic, free of network variance and repeatable
by anyone who clones the repository. Nothing in the corpus was written for the benchmark.

**Ground truth.** Each task carries a `pin`: a string that appears in exactly one document of
the corpus. `--verify` checks that on every run, which is what makes "the agent answered
correctly" mean "the agent retrieved the right document", not "the model already knew".

**Conditions.** Two knobs, because the answer depends on both and hiding that would be the
lie:

- `--retrieval precise|noisy`. Precise indexes and shows curated section headings, so the
  right document usually ranks first and announces itself. Noisy ranks by body frequency and
  shows snippets, which is what a real retriever over real pages gives you.
- `--doc-size small|large`. Small leaves page-sized documents; large folds sections until
  documents are the size of an official PDF.

**Statistics.** Each squire run is paired with the run of the same task and repetition
without it, and the reported change is a paired bootstrap over those pairs, 2,000 resamples,
fixed seed. Means alone would mix the effect with the run-to-run variance of the agent's
search path, which is large.

**Cost control.** A turn cap and an input-token cap per run, a running total printed as it
goes, and `--max-usd` aborts the sweep.

## What the A/B found, and one thing it fixed

Results are in `ab/results/`, with every run recorded in `runs.json`.

The first honest finding is a null one: at page-sized documents the cost effect is not
distinguishable from zero, while the latency cost is real. The break-even arithmetic in
`../docs/savings.md` predicts exactly that, and the large-document condition is there to
test the other half of the prediction.

The second is a bug this benchmark caught in the library itself. Triage judged a
10,000-character document on its first 1,500 characters, decided the preamble did not address
the purpose, and dropped the one document holding the answer. The agent re-fetched it, got it
dropped again, hit its turn cap and produced nothing, at twice the cost. `sanchopanza.text.
excerpt` now sends the head plus the window that best matches the purpose. Documents that
already fit are unchanged, so no bench number moved, which the replay test enforces.

That is the argument for running an end-to-end benchmark even when the decision-level numbers
look good: the decisions were fine, the way they were wired to long documents was not.
