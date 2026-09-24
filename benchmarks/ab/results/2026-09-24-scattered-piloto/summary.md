# End-to-end A/B: source redundancy on and off (claude-sonnet-5, scattered retrieval, small documents)

Same agent, same tasks, same prompts, same tools, same thinking and effort. The only
difference between the arms is that `fetch` passes the page through the squire before
it enters the context. Corpus and tasks are in this directory; the run is offline apart
from the model calls, so anyone can repeat it.

Retrieval condition `scattered`: body-frequency ranking over a wide result list, with the agent told the answer is spread across documents. This is the fetch-heavy condition: the one where a lever that keeps redundant sources out of the context has something to keep out.

Total spend of this run: 0.2405 USD.

| | Without the squire | With the squire | Change |
|---|---|---|---|
| Runs | 2 | 2 | |
| Correct answers | 2/2 | 2/2 | |
| Input tokens, mean | 33,546 | 15,980 | **-52.4 %** |
| Output tokens, mean | 1,190 | 918 | |
| Model cost, mean | 0.07899 USD | 0.04114 USD | -47.9 % |
| Squire cost, mean | 0 | 0.000121 USD | |
| **Total cost, mean** | **0.07899 USD** | **0.04127 USD** | **-47.8 %** |
| Wall time, mean | 16.1 s | 13.1 s | -18.6 % |
| Documents fetched, mean | 6 | 4 | |
| Of those, dropped by triage | 0 | 0 | |
| Of those, dropped as redundant | 0 | 0 | |
| Turns, mean | 6 | 4 | |

## Paired comparison

Each run with the squire is paired with the run of the same task and repetition without it, 2 pairs. The interval is a 95 % paired bootstrap over those pairs, 2,000 resamples, fixed seed.

| Measure | Change with the squire | 95 % CI |
|---|---|---|
| Input tokens | **-52.4%** | [-61.9%, +0.0%] |
| Total cost | **-47.8%** | [-58.9%, -1.0%] |
| Wall time | -18.2% | [-27.3%, +5.6%] |

## Per task

| Task | Correct without / with | Input tokens without / with | Total cost without / with |
|---|---|---|---|
| spread-adapters | 1/1 - 1/1 | 10,373 - 10,373 | 0.03037 - 0.03007 USD |
| spread-costs | 1/1 - 1/1 | 56,718 - 21,586 | 0.12762 - 0.05246 USD |

## What this does and does not say

It measures one lever, source redundancy, on one corpus, with one retriever and one
model. It does not measure model routing, search routing, the citation check or the shell
guard, none of which are exercised here. The corpus documents average a few hundred to
a couple of thousand tokens; the effect scales with document size, and the arithmetic
for other sizes is in `docs/savings.md`.

Quality is measured as an exact-substring match against figures that appear in exactly
one document of the corpus, verified by `--verify`. That catches an answer that lost the
fact; it does not catch an answer that is worse in ways a reader would notice.

**The lever dropped nothing in any run, so this comparison is uninformative about
it.** When no page is dropped the squire arm hands the model exactly the bytes the
bare arm hands it, so the two arms are the same experiment run twice and every
difference above is the agent's run-to-run variance in its search path. Read the
numbers as a measurement of that variance, not of the lever.
