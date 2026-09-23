# End-to-end A/B: page triage on and off (claude-sonnet-5, noisy retrieval, large documents)

Same agent, same tasks, same prompts, same tools, same thinking and effort. The only
difference between the arms is that `fetch` passes the page through the squire before
it enters the context. Corpus and tasks are in this directory; the run is offline apart
from the model calls, so anyone can repeat it.

Retrieval condition `noisy`: body-frequency ranking, results shown as snippets instead of curated headings, and the agent is told to corroborate. A real retriever over real pages looks like this; the curated section headings of this corpus are the artifact.

Total spend of this run: 0.9479 USD.

| | Without the squire | With the squire | Change |
|---|---|---|---|
| Runs | 24 | 24 | |
| Correct answers | 21/24 | 21/24 | |
| Input tokens, mean | 8,409 | 8,430 | **+0.2 %** |
| Output tokens, mean | 294 | 281 | |
| Model cost, mean | 0.01976 USD | 0.01967 USD | -0.5 % |
| Squire cost, mean | 0 | 0.000065 USD | |
| **Total cost, mean** | **0.01976 USD** | **0.01973 USD** | **-0.2 %** |
| Wall time, mean | 5.4 s | 6.0 s | +11.1 % |
| Documents fetched, mean | 1 | 1.08 | |
| Of those, dropped by triage | 0 | 0.17 | |
| Turns, mean | 3.04 | 3.04 | |

## Paired comparison

Each run with the squire is paired with the run of the same task and repetition without it, 24 pairs. The interval is a 95 % paired bootstrap over those pairs, 2,000 resamples, fixed seed.

| Measure | Change with the squire | 95 % CI |
|---|---|---|
| Input tokens | **+0.3%** | [-6.2%, +11.6%] |
| Total cost | **-0.2%** | [-6.2%, +10.5%] |
| Wall time | +11.6% | [+4.1%, +18.9%] |

## Per task

| Task | Correct without / with | Input tokens without / with | Total cost without / with |
|---|---|---|---|
| breakeven | 3/3 - 3/3 | 5,484 - 5,483 | 0.01395 - 0.01352 USD |
| classify | 3/3 - 3/3 | 12,185 - 14,349 | 0.02697 - 0.03159 USD |
| cost | 3/3 - 3/3 | 6,527 - 6,484 | 0.01626 - 0.01612 USD |
| dag | 3/3 - 3/3 | 11,511 - 11,508 | 0.02637 - 0.02638 USD |
| entity | 3/3 - 3/3 | 11,302 - 11,299 | 0.02499 - 0.02504 USD |
| injection | 3/3 - 3/3 | 14,955 - 12,997 | 0.03422 - 0.02987 USD |
| toolselect | 0/3 - 0/3 | 1,950 - 1,950 | 0.00560 - 0.00543 USD |
| viviendas | 3/3 - 3/3 | 3,360 - 3,373 | 0.00974 - 0.00990 USD |

## What this does and does not say

It measures one lever, page triage, on one corpus, with one retriever and one model.
It does not measure model routing, search routing, the citation check or the shell
guard, none of which are exercised here. The corpus documents average a few hundred to
a couple of thousand tokens; the effect scales with document size, and the arithmetic
for other sizes is in `docs/savings.md`.

Quality is measured as an exact-substring match against figures that appear in exactly
one document of the corpus, verified by `--verify`. That catches an answer that lost the
fact; it does not catch an answer that is worse in ways a reader would notice.
