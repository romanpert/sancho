# What it costs and when it pays

Every number in the **Measured** sections comes from the recorded public bench in this
repository and replays with `sanchopanza bench --provider recorded`. Token counts are exact,
from Anthropic's token counter, not chars divided by four. Model prices are Anthropic's
list prices as of 2026-06-24 and are the only inputs that are not measured here.

**Read this first: there is no end-to-end saving figure in this document, because we have
not run that experiment.** What follows is what the layer costs, what it keeps out, and the
arithmetic that says when the second exceeds the first. The experiment that would license a
headline percentage is described at the bottom.

| Model | Input $/MTok | Output $/MTok |
|---|---|---|
| Claude Opus 5 | 5.00 | 25.00 |
| Claude Sonnet 5 | 2.00 | 10.00 |
| Claude Haiku 4.5 | 1.00 | 5.00 |
| Jev 1.13 (the decision model) | 0.042 | free |

## Measured: what the decision layer costs

The public bench is 227 decisions over 154,886 input tokens,
and it cost **0.0065 USD**. That is **28.7 millionths of a
dollar per decision**, output included, because this model's output is free.

The same input tokens, priced as input alone and ignoring any output the model would have
had to write:

| Priced as | Cost | Multiple |
|---|---|---|
| claude-opus-5 | 0.7744 USD | 119x |
| claude-sonnet-5 | 0.3098 USD | 48x |
| claude-haiku-4-5 | 0.1549 USD | 24x |
| Jev 1.13 | 0.0065 USD | 1x |

Those multiples are a floor. A generative model also pays for the tokens it writes, and a
measured comparison on 156 of these cases against Claude Haiku 4.5 with tool-forced output
came out at **49x** (0.0048 against 0.2337 USD) with three times the latency. See the paper,
Section 5.6.

## Measured: what page triage keeps out

On the 16 triage cases, the squire dropped 7.
That is **898 tokens that never entered the context** against
1,517 that did, so 37% of the text was kept out.
Deciding it cost 0.000712 USD.

| Priced as | Value of what was dropped | Times the cost of deciding |
|---|---|---|
| claude-opus-5 | 0.00449 USD | 6.3x |
| claude-sonnet-5 | 0.00180 USD | 2.5x |
| claude-haiku-4-5 | 0.00090 USD | 1.3x |

**Be careful with that table, and do not quote it as a saving.** The bench pages are
excerpts, averaging 151 tokens. At that size the lever barely pays for itself:
2.5x at Sonnet 5 prices, 1.3x at Haiku prices. A real fetched page is one to two orders of
magnitude larger, which is the whole point of the next section.

## The number that travels: break-even page size

One triage decision costs 44.5 millionths of a dollar. At the measured
drop rate of 37%, the expected tokens kept out of a page of T tokens is
0.37 x T. Triage pays for itself when that is worth more than the decision:

| The large model is | A page pays for its own triage above |
|---|---|
| claude-opus-5 | **24 tokens** |
| claude-sonnet-5 | **60 tokens** |
| claude-haiku-4-5 | **120 tokens** |

So on a Sonnet-class orchestrator, any page over about 60 tokens is worth triaging. Below
is what the same arithmetic gives for pages of a realistic size, per page:

| Page | Tokens | Expected tokens kept out | Value at Sonnet 5 | Cost of deciding | Net |
|---|---|---|---|---|---|
| news snippet | 500 | 186 | 0.00037 USD | 0.000044 USD | **8x** |
| full article | 2,000 | 744 | 0.00149 USD | 0.000044 USD | **33x** |
| official PDF | 10,000 | 3,720 | 0.00744 USD | 0.000044 USD | **167x** |

The same shape applies to a job. A round that fetches 40 pages of 2,000 tokens spends
0.0018 USD on triage and keeps about 29,760 tokens out of the context, worth 0.0595 USD at Sonnet 5 input prices. Whether those
tokens would have changed the deliverable is exactly what the end-to-end experiment has to
answer, and it is not answered here.

## Measured: model routing and search routing

On 20 delegation cases the squire chose 7 light, 9 default and 4 deep, and 7 of the light choices carried confidence 0.75 or above,
which is the threshold at which the policy acts. Deciding all twenty cost 0.000527 USD, that is 26.4 millionths per task.

Claude Haiku 4.5 costs half of Claude Sonnet 5 per token, input and output alike. So a
subtask moved down one tier costs half of what it would have. With 35 % of tasks moving
down, routing pays for itself once a subtask is larger than:

| The default tier is | A subtask pays for its own routing above |
|---|---|
| claude-opus-5 | **30 tokens** |
| claude-sonnet-5 | **75 tokens** |

Any real subtask is thousands of tokens, so this lever is effectively free to run. What it
is not is free of risk: the risk is quality, not money, which is why the policy only acts
above 0.75 confidence and never sends a task about an identifiable person to the light tier.

On 18 search cases it sent 11 to a free engine, cut
3 as repeats and left 4 for the paid search,
for 0.000792 USD. The saving there is whatever your search
provider charges per query, which we cannot measure for you.

## The end-to-end A/B, now that it has been run

Everything above is arithmetic about tokens. It does not say the deliverable gets cheaper or
better. That question needed its own experiment, and `benchmarks/ab/` is it: the same agent,
the same eight tasks, the same prompts, tools, model, thinking and effort, one arm with page
triage and one without, over a fixed corpus, with each squire run paired against the run of
the same task and repetition without it.

**On page-sized documents the cost difference was not distinguishable from zero.** Forty
pairs, Claude Sonnet 5, noisy retrieval:

| Measure | Change with the squire | 95 % paired bootstrap |
|---|---|---|
| Input tokens | -3.3 % | [-13.6 %, +11.2 %] |
| Total cost | -1.3 % | [-11.2 %, +12.6 %] |
| Wall time | **+16.4 %** | [+4.2 %, +30.5 %] |

Answer quality did not suffer: 38 of 40 correct without the squire, 39 of 40 with it. The
latency cost, on the other hand, is real and its interval excludes zero: an extra round trip
per fetched page, plus the occasional extra fetch.

That is the honest headline at this document size, and it agrees with the break-even table:
with documents averaging a couple of thousand characters and 0.45 pages dropped per run, the
expected saving is a rounding error next to the run-to-run variance of the agent's own search
path. The `--doc-size large` condition tests the other half of the prediction, that the effect
grows with document size; results are in `benchmarks/ab/results/`.

**What to quote, then.** The cost per decision and the break-even, which are measured. The
safety and quality numbers from the paper, which are measured. Not a saving percentage,
because at ordinary document sizes we looked for one and it was not there.

**What the A/B was worth anyway.** It found a real bug. Triage was judging a 10,000-character
document on its first 1,500 characters, deciding the preamble did not address the purpose and
dropping the one page that held the answer; the agent re-fetched it, hit its turn cap and
returned nothing at twice the cost. `sanchopanza.text.excerpt` now sends the head plus the
window that matches the purpose. No decision-level number moved, because documents that
already fit are unchanged. The decisions were fine; the way they were wired to long documents
was not, and only an end-to-end run could show that.
