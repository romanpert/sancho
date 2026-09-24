# Fifty cases per binary point, a second annotator, and what a precision target costs

Run of 2026-09-24. 212 new cases, `jev-1.13.0`, **0.0060 USD**, 28.3 millionths per decision -
the same per-decision figure as the public run and the 124-case run, now on a third
distribution.

This closes item 2 of `docs/paper.md` Section 8 and item 2 of `docs/where-it-pays.md`
Section 6: *"fifty cases and a second annotator per new point, then thresholds set the way
Google sets them: per point, to a target precision, reported as recall@X."*

**It closes it with a negative answer, which is the useful part: the thresholds must not
move, and now there is a number saying why.**

| | |
|---|---|
| New cases | 212, in `benches/{loop,memory,graph-build,retrieval}-b.jsonl` |
| Points taken to 50 | `goal_met`, `repeats_check`, `memory_write`, `recall`, `extract_gate`, `redundant_page` |
| Recording | `fixtures/new-points-50.jsonl`, replays for free |
| Cost of the evaluator | 0.0060 USD for 212 decisions |
| Cost of the second annotator | see below; it is three orders of magnitude more |

The original 124-case bench is untouched in its own files and its own fixture, so the run
published in paper Section 5.10 stays reproducible exactly as it was.

---

## 1. The bench was made harder on purpose, and it worked

The first batch scored 14/14, 12/12, 14/14 and 16/16 on four of these six points. A bench
nothing fails measures nothing, so these cases concentrate on the families that are real
failure modes rather than word games: partial completion that reads as complete, effort
narrated as result, corroboration mistaken for repetition, staleness, boilerplate that
nonetheless carries an instance, and facts that are true and durable and still not worth
storing because the source is already in hand. Each file's header names its families.

Agreement on the new cases, under the shipped policy and at a plain 0.5 cut:

| Point | n | Shipped policy | At a 0.5 cut | AUC | Brier | ECE |
|---|---|---|---|---|---|---|
| extract_gate | 34 | 30/34 | 30/34 | 0.97 | 0.071 | 0.073 |
| goal_met | 36 | 35/36 | 35/36 | 0.99 | 0.038 | 0.109 |
| memory_write | 34 | 26/34 | 31/34 | 0.99 | 0.095 | 0.227 |
| recall | 36 | 36/36 | 36/36 | 1.00 | 0.008 | 0.076 |
| redundant_page | 34 | 26/34 | 33/34 | 1.00 | 0.035 | 0.139 |
| repeats_check | 38 | 37/38 | 37/38 | 1.00 | 0.030 | 0.133 |
| **total** | **212** | **190** | **202** | | | |

The gap the 0.2.0 fix closed on the old cases reopens on the hard ones, and it is entirely
`memory_write` (26 against 31) and `redundant_page` (26 against 33). It is no longer the
hidden-double-gate defect, which is gone: it is single thresholds at 0.70 and 0.80 declining
to act on cases the model orders correctly. AUC is 0.97 to 1.00 everywhere, so every error is
a threshold, not an ordering.

Every one of the 12 errors under the policy is a refusal to act. `memory_write` fails only by
declining to store something it should have stored; `redundant_page` fails only by keeping a
page it could have dropped.

## 2. Five labels were corrected, and both sets of numbers are published

On the question's own criteria, not because the model disagreed. Before the corrections the
policy scored 185/212 and a 0.5 cut 197/212; after, 190 and 202. The evaluator's answers were
not re-run and did not change.

**`rd-19`, `rd-23`, `rd-35`, `rd-42` (drop to keep).** They were authored on the theory that
a page with no bearing on the purpose "adds nothing". The question asks whether the text
carries *"no new figure, date, name, outcome, qualification or source"* that `known` lacks,
and all four carry several: a magnitude and a depth, a founding year and a headcount, a fleet
size, a set of metro lines. They are off-purpose, not redundant. `decide_redundancy` is never
handed a relevance signal, because dropping an off-topic page is page triage's job and triage
runs first; the original labels were the annotator making one point do two jobs.

The check that this was a correction and not capitulation: after relabelling, **AUC on
`redundant_page` rises from 0.97 to 1.00**. Moving labels to match a model does not generally
make its ordering perfect. `rd-15` in the first batch stays `drop` and is not the same case -
it carries earthquake safety advice and no fact of any kind, so it satisfies the criterion.

**`eg-41` (skip to extract).** A cadastral reference names one specific property and the
chunk states its surface, its year and its share, which is exactly "names at least one
instance and says something about it".

**`eg-47` was left alone** although the evaluator missed it at confidence 0.68. It is a
breadcrumb naming a resolution number and no company or person, and the question's `false`
side lists section paths explicitly. The label is arguable both ways, and moving an arguable
label to match the model is how a bench stops measuring anything.

## 3. What a precision target actually costs, which is the result

`benchmarks/thresholds.py` derives a threshold on one result set and reports every number
from another, and requires the **95 % Wilson lower bound** of precision to clear the target
rather than the point estimate. The second rule is what turns "target precision" into a claim
that can fail, and it changes the answer completely.

The first attempt used the observed precision, as the plan implied. It produced thresholds of
0.13, 0.23 and 0.08, and out of sample two of six points missed their own 90 % target by 10
and 11 points. That is not a threshold, it is an artefact of reading 100 % off a dozen cases.

With the lower bound, the sample-size floor is pure arithmetic:

| Target precision | Acted cases needed at perfect observed precision | Labelled cases per point |
|---|---|---|
| 80 % | 16 | about 32 |
| 90 % | 35 | about 70 |
| 95 % | 73 | about 146 |

**Fifty cases per point supports an 80 % precision target and nothing above it.** The plan in
paper Section 8 asked for fifty cases and then for thresholds at a target precision, without
noticing that the two halves of the sentence are inconsistent for any target worth having.

Deriving on the new cases and reporting on the original ones:

| Point | Acts by | Shipped | Target | Derived | Precision (held out) | Recall | Agreement derived / shipped |
|---|---|---|---|---|---|---|---|
| goal_met | true | 0.50 | 80 % | 0.34 | 100 % | 100 % | 14/14 / 14/14 |
| repeats_check | true | 0.50 | 80 % | 0.51 | 100 % | 100 % | 12/12 / 12/12 |
| recall | skip | 0.25 | 80 % | 0.13 | 100 % | 100 % | 14/14 / 14/14 |
| memory_write | store | 0.70 | 80 % | unreachable at n=34 | - | - | - / 11/16 |
| redundant_page | drop | 0.80 | 80 % | unreachable at n=34 | - | - | - / 14/16 |
| extract_gate | skip | 0.25 | 80 % | unreachable at n=34 | - | - | - / 15/16 |
| any point | | | 90 %, 95 % | unreachable at this n | - | - | - |

Three of six points reach an 80 % target. In all three the derived threshold scores exactly
what the shipped one scores out of sample, so there is nothing to change. The three that
cannot reach it include both points carrying the whole policy gap.

**So no threshold moves in this run.** Not out of the standing caution, but because the
measurement says the sample cannot support the move. The two points that would benefit,
`memory_write` and `redundant_page`, are precisely the two where the evidence is thinnest.

## 4. The second annotator, and the thing it separated

Annotator 1 is the author, who labelled every case before any decision was run. Annotator 2
is `claude-opus-5`, given the same question and the same criteria the evaluator receives -
rendered from the package's own question builders, so the comparison is against the literal
question and not a paraphrase - and blind to both the first label and the evaluator's answer.
Its labels are in `annotator-2.jsonl`; `benchmarks/agreement.py` reproduces the table.

| Point | n | A1 vs A2 | Cohen's kappa | A1 vs evaluator | A2 vs evaluator |
|---|---|---|---|---|---|
| extract_gate | 34 | 91 % | 0.82 | 88 % | 85 % |
| goal_met | 36 | 97 % | 0.94 | 97 % | 100 % |
| memory_write | 33 | 100 % | 1.00 | 79 % | 79 % |
| recall | 36 | 100 % | 1.00 | 100 % | 100 % |
| redundant_page | 34 | 91 % | 0.80 | 76 % | 79 % |
| repeats_check | 38 | 100 % | 1.00 | 97 % | 97 % |
| **all** | **211** | **97 %** | **0.96** | **90 %** | **91 %** |

One case, `mw-32`, exhausted its retries and carries no second label; it is excluded rather
than counted as agreement.

**The evaluator is as close to the blind annotator as it is to the author** - 91 % against
90 %. That is the comparison worth keeping: it is not being scored against the person who
wrote its questions.

**And the second annotator separates two diagnoses that agreement alone confuses.**

- `memory_write` has **kappa 1.00**: the two annotators agree on all 33 cases, so none of
  them is ambiguous. The evaluator still scores 79 %. Its errors are therefore not on hard
  cases, they are the 0.70 threshold declining to act on cases nobody disputes. This is the
  clearest evidence in the run that that threshold is too strict - and Section 3 says the
  sample is still too small to move it.
- `redundant_page` (kappa 0.80) and `extract_gate` (kappa 0.82) are the two lowest, and are
  also where the evaluator scores worst, 76 % and 88 %. Those errors cluster on the cases the
  annotators themselves argue about. That is a question-definition problem, not a threshold
  one, and adding cases of the same shape will not fix it.

Where both annotators agree (204 cases) the evaluator agrees with them 92 % of the time.
Where they disagree (7 cases) it sides with annotator 1 three times and annotator 2 four
times, which is what a coin does, and is the honest summary of those seven.

### The seven disputed cases, including one against the author

| Case | Point | Annotator 1 | Annotator 2 | Evaluator |
|---|---|---|---|---|
| eg-25 | extract_gate | extract | skip | extract |
| eg-35 | extract_gate | extract | skip | extract |
| eg-47 | extract_gate | extract | skip | **skip** |
| gm-50 | goal_met | true | false | **false** |
| rd-33 | redundant_page | drop | keep | **keep** |
| rd-37 | redundant_page | drop | keep | **keep** |
| rd-42 | redundant_page | **keep** | drop | keep |

Three of these deserve saying out loud rather than burying:

- **`eg-47` and `gm-50` are cases this run counts as evaluator errors while the blind
  annotator agreed with the evaluator, not with the author.** `eg-47` was deliberately left
  unrelabelled in Section 2 as "arguable in both directions"; the second annotator
  independently took the other direction, which is evidence that it is arguable rather than
  evidence that the author was right. `gm-50` turns on whether a *multa* and an
  *indemnizacion* are the same thing, and the first batch's `gm-01` assumes they are. Both
  are kept as they are - a label is not changed because a model disagrees with it - and both
  are recorded here as disputed.
- **`rd-42` is the one that went against the author's own correction.** Section 2 relabelled
  it from `drop` to `keep` along with three siblings; the blind annotator, which never saw
  either label, said `drop`. It is the weakest of those four: a page explaining how to reach
  a building by metro is neither a restatement of the known address nor a page carrying facts
  bearing on it, so it fits neither side of the question cleanly. The other three
  corrections, `rd-19`, `rd-23` and `rd-35`, drew no dispute.

**This is not two independent human annotators**, and nothing here should be read as if it
were. Two failure modes it cannot see: a criterion that is wrong in the same way for a model
and for the author who wrote it in the model's idiom, and a case whose wording steers both.
A kappa of 0.96 between an author and a model given that author's own criteria is a weaker
fact than a kappa of 0.96 between two people. Where the paper uses these numbers it says so.

## 5. What this does not settle

- `memory_collision` and `edge` are not extended. They have four and three labels, an
  abstention band, and in `memory_collision` a `duplicate` branch that has never fired.
  Adding cases of the same shape would not move either; both need their own treatment.
- The 80 %-target result rests on 34 to 38 derivation cases and 12 to 20 held-out ones. The
  held-out halves are small enough that "100 % precision" there carries its own wide interval,
  by exactly the argument this file makes about the derivation half.
- Nothing here is end to end. `redundant_page` in particular was asked six times in the
  fetch-heavy A/B pilot of the same day and dropped nothing, so its only evidence remains
  decision-level (`benchmarks/ab/results/2026-09-24-scattered-piloto`).

## Reproducing

```
sanchopanza bench benches/loop-b.jsonl benches/memory-b.jsonl \
  benches/graph-build-b.jsonl benches/retrieval-b.jsonl \
  --provider recorded --fixture fixtures/new-points-50.jsonl

python benchmarks/thresholds.py --derive docs/results/2026-09-24-fifty --eval <other run>
```

Both are free. Re-recording against the live model costs 0.006 USD and needs
`TYPESAFE_API_KEY`.
