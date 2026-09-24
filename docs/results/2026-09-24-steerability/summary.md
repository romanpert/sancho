# Steerability: what moved, what did not, and why this is not a pitch

**2026-09-24, Jev 1.13, 28 cases in 14 flipped pairs, 28,158 input tokens, 0.00118 USD.**
Replays for free from `fixtures/steerability.jsonl`; pinned by `tests/test_steerability.py`.

## Why this bench exists

A vendor's LinkedIn post frames the choice before an LLM as: a cross-encoder that "cannot be
steered", an LLM reranker at "27x cost", or a decision model that is "steerable and cheap".
We are the decision model in that picture, so the claim flatters us and we had to check it
rather than repeat it.

**The claim is false as stated, and we established that before running anything.** In 2026
instruction-following is a shipped, priced feature of commercial rerankers. Voyage sells
`rerank-2.5` and `rerank-2.5-lite` as instruction-following, with the instruction appended to
the query in natural language; their own worked example is our pitch nearly word for word
("retrieve regulatory documents and legal statutes, not court cases"). ZeroEntropy's
`zerank-2` takes instructions and business context. Contextual AI shipped one in March 2025
covering recency, document type and source priority. Four benchmarks exist to measure the
capability: MAIR, IFIR, FollowIR, InstructIR. And every one of those rerankers is cheaper per
token than the model we use: 0.02 and 0.025 USD/MTok against 0.042.

So the honest question is not "can only we be steered" but "**what, if anything, do we do
here that a steerable reranker does not**". This bench is a first, small answer, and it is
not sufficient to claim a product.

## The design

Every pair holds the **document** and the **topic** fixed and changes only the **criterion**,
so the correct answer flips. The metric is **pair accuracy**: both sides right, or the pair
does not count.

That metric has teeth because of an arithmetic bound, not an experiment. A scorer whose
inputs are only (query, document) cannot move when both are held fixed, so it answers both
sides identically and scores **0 % pair accuracy by construction**. That covers a plain
cross-encoder and embedding similarity. It does **not** cover an instruction-following
reranker, which is why the fair baseline is missing rather than beaten (see below).

## Results

| | |
|---|---|
| Pairs | 14 |
| **Both sides right** | **11/14 (79 %)** |
| The answer changed when only the criterion changed | 11/14 |
| Per case | 25/28 |
| Cost | 0.00118 USD, 42 millionths per decision |

The three failures, and each one is a different kind of failure:

| Pair | Criterion | What happened |
|---|---|---|
| st-01 | "official primary sources ... not press that cites them" | Kept a newspaper. Relevance answered 0.98, correctly: the article *is* about the topic. **The provenance answer was in the same decision** - `source_kind` came back `news` at confidence 1.00 - and the policy threw it away. |
| st-09 | "material in Spanish we can quote directly" | Kept an English-language document. The language of the document is not something the relevance question asks about, and nothing else in the decision carries it. |
| st-14 | "rulings from 2025 onward" | Kept a 2016 ruling. Declared a negative control **before** the run, because this model class reads dates as text. Its twin st-13, also date-based, passed: the weakness is real and it is not absolute. |

## What we changed because of it

**st-01 was a design error, not a model error, and it is fixed.** `triage.decide` now takes
`allowed_kinds` / `denied_kinds` and filters on the source kind the decider already returned,
in code, at no extra call and no extra token. The same recorded decision that kept the
newspaper now drops it, which `tests/test_steerability.py` pins.

The rule this generalises to is the package's oldest one, applied somewhere new: **a
criterion that a Choice question already answers does not belong in free-text purpose
prose**. Choice is also the best-calibrated primitive in this model class (ECE 0.035 against
0.14 for Truth), so routing a requirement through it is both cheaper and steadier. Across
these 28 cases `source_kind` came back with mean confidence 0.91 and separated news,
official records, corporate, data APIs and academic cleanly.

**st-09 is an open gap.** There is no question in the triage point about the language of the
document. Adding one is cheap; it has not been measured, so it has not been added.

**st-14 stays broken on purpose.** A date range is a comparison, and comparisons belong in
code. A harness that needs one should filter on the document's date, which it usually has
from the crawl, not ask a model that reads dates as text.

## What this does not show

- **No baseline was run.** The comparison that matters - an instruction-following reranker
  over the same 14 pairs - has not been done. Until it is, this file says what our layer
  does, not what it does better.
- **Fourteen pairs, one annotator, one language, one domain.** Every caveat in the paper's
  Section 7 applies here with less data behind it.
- **It measures a gate, not a ranking.** A reranker returns an ordering over 100 documents in
  one pass; this returns an independent judgment per document, which is N calls, and
  pointwise scoring is the known-worst architecture for ranking quality.

## The hypothesis worth testing next, stated so it can fail

Our architectural difference is not "a calibrated score per document", which a reranker
vendor already sells, with published thresholds, at 60 % of our price. It is **several
independent typed questions asked about one state in a single pass**: is it an official
source, does it state a figure, is it an opinion piece, is it inside the date range. A
reranker answers one blended instruction, or runs once per criterion at N times the cost.

The literature leaves exactly one door open: **exclusion**. Models solve at most one ExcluIR
query in eight (arXiv 2502.13506, SIGIR 2025), and negation is where instruction-following
degrades. Five of our fourteen criteria are exclusions ("not press", "not third-party
summaries", "not opinion", "not passing mentions", "not what the company says about itself")
and **four of those five pairs passed**. Four of five is a hint, not a result.

The experiment that would settle it: 300-500 queries over one corpus, each carrying 4-8
orthogonal non-topical criteria, gold-labelled by two annotators, with three arms on the same
top-100 candidates - (A) an instruction-following reranker with the criteria concatenated
into one instruction and thresholded, (B) the same reranker run once per criterion and
AND-ed, which is the honest steerable baseline and costs N times as much, (C) this layer, one
pass, every criterion its own typed question. The metric is **set-level precision and recall
of the gate**, not nDCG, plus cost per query, p95 latency, and an out-of-domain split to see
whether absolute thresholds survive distribution shift or need percentile gates like
everyone else's. There is a product only if (C) beats (A) on gate precision **and** beats (B)
on cost at equal precision. On current evidence (A) is the favourite for anything that is a
soft preference rather than a hard constraint.
