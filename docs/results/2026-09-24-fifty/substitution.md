# The same judgments, made two ways

211 judgments from `2026-09-24-fifty`, each answered independently by a calibrated non-generative evaluator and by a frontier generative model given the same question, the same criteria and the same state. Neither saw the bench labels.

| | Evaluator, shipped policy | Evaluator, plain 0.5 cut | Generative model |
|---|---|---|---|
| Model | `jev-1.13.0` | same | `claude-opus-5` |
| Judgments | 212 | 212 | 212 |
| Agreement with the bench labels | 190/211 = 90% | 202/211 = 96% | 204/211 = 97% |
| Total cost | 0.0060 USD | same | 0.7884 USD |
| Cost per judgment | 28.4 millionths | same | 3719 millionths |
| Median latency | 250 ms | same | 2731 ms |
| Wall clock, all judgments | - | - | 618 s of model time |

**131x cheaper per judgment, 10.9x faster, and 2 decisions less accurate** than the frontier model at a plain cut - 14 under the thresholds actually shipped.

## What this is

Substitution, measured end to end on a real set of judgments rather than argued from a price list, and it is not a tie. The frontier model is the more accurate judge: 204/211 against 190/211 under the shipped policy. But most of that gap is the thresholds and not the model - at a plain 0.5 cut the evaluator reaches 202/211, and the remaining difference is 2 decisions.

So the trade is stated honestly like this: **the cheap evaluator gives up a small amount of accuracy and buys back 131x the price and 10.9x the latency.** Whether that trade is worth taking is a property of the decision, not of the models: it is obviously worth it for a gate in front of a generative pass, and obviously not for a judgment that is the deliverable. The size of the gap is also the size of the prize for deriving better thresholds, which is why `benchmarks/thresholds.py` exists.

## What it is not

- It is not a claim that the evaluator is as good as the generative model at anything else. These are closed-vocabulary judgments over a supplied state, which is the shape the package claims and the only shape it claims.
- The generative model is run at `low` effort answering in one word, which is close to the cheapest a frontier model can be asked to do this. The ratio would be larger at any realistic effort setting, not smaller.
- Neither side caches: a per-decision prompt is below the minimum cacheable prefix. A judgment made inside a long warm conversation would be read at the cached rate, which is the correction `docs/where-it-pays.md` applies to *avoidance* and which does not apply here, because these calls are separate requests either way.
- Prices are list prices (5.00 in / 25.00 out USD per MTok for `claude-opus-5`), so this is arithmetic over reported tokens and not a bill.
