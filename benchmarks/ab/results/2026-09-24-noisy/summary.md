# End-to-end A/B: page triage on and off (claude-sonnet-5, noisy retrieval)

Same agent, same tasks, same prompts, same tools, same thinking and effort. The only
difference between the arms is that `fetch` passes the page through the squire before
it enters the context. Corpus and tasks are in this directory; the run is offline apart
from the model calls, so anyone can repeat it.

Retrieval condition `noisy`: body-frequency ranking, results shown as snippets instead of curated headings, and the agent is told to corroborate. A real retriever over real pages looks like this; the curated section headings of this corpus are the artifact.

Total spend of this run: 2.0709 USD.

| | Without the squire | With the squire | Change |
|---|---|---|---|
| Runs | 40 | 40 | |
| Correct answers | 38/40 | 39/40 | |
| Input tokens, mean | 10,909 | 10,550 | **-3.3 %** |
| Output tokens, mean | 423 | 451 | |
| Model cost, mean | 0.02605 USD | 0.02561 USD | -1.7 % |
| Squire cost, mean | 0 | 0.000111 USD | |
| **Total cost, mean** | **0.02605 USD** | **0.02572 USD** | **-1.3 %** |
| Wall time, mean | 7.6 s | 8.9 s | +17.1 % |
| Documents fetched, mean | 1.77 | 1.98 | |
| Of those, dropped by triage | 0 | 0.45 | |
| Turns, mean | 4.17 | 4.3 | |

## Paired comparison

Each run with the squire is paired with the run of the same task and repetition without it, 40 pairs. The interval is a 95 % paired bootstrap over those pairs, 2,000 resamples, fixed seed.

| Measure | Change with the squire | 95 % CI |
|---|---|---|
| Input tokens | **-3.3%** | [-13.6%, +11.2%] |
| Total cost | **-1.3%** | [-11.2%, +12.6%] |
| Wall time | +16.4% | [+4.2%, +30.5%] |

## Per task

| Task | Correct without / with | Input tokens without / with | Total cost without / with |
|---|---|---|---|
| breakeven | 5/5 - 5/5 | 7,063 - 6,855 | 0.01805 - 0.01819 USD |
| classify | 5/5 - 5/5 | 16,716 - 16,509 | 0.03792 - 0.03779 USD |
| cost | 3/5 - 4/5 | 9,085 - 8,978 | 0.02321 - 0.02338 USD |
| dag | 5/5 - 5/5 | 18,965 - 14,771 | 0.04352 - 0.03593 USD |
| entity | 5/5 - 5/5 | 12,151 - 15,427 | 0.02818 - 0.03598 USD |
| injection | 5/5 - 5/5 | 16,045 - 14,469 | 0.03760 - 0.03397 USD |
| toolselect | 5/5 - 5/5 | 3,878 - 3,878 | 0.01008 - 0.01023 USD |
| viviendas | 5/5 - 5/5 | 3,373 - 3,514 | 0.00986 - 0.01028 USD |

## What this does and does not say

It measures one lever, page triage, on one corpus, with one retriever and one model.
It does not measure model routing, search routing, the citation check or the shell
guard, none of which are exercised here. The corpus documents average a few hundred to
a couple of thousand tokens; the effect scales with document size, and the arithmetic
for other sizes is in `docs/savings.md`.

Quality is measured as an exact-substring match against figures that appear in exactly
one document of the corpus, verified by `--verify`. That catches an answer that lost the
fact; it does not catch an answer that is worse in ways a reader would notice.
