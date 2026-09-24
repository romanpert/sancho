# Bench results

Cases: 70 - decision calls: 70 - input tokens: 48260 - cost: 0.0020 USD

| Point | n | Coverage | Agreement when deciding | Wilson 95 % | Median latency |
|---|---|---|---|---|---|
| memory_write | 34 | 100% | 26/34 = 76% | [60%, 88%] | 250 ms |
| recall | 36 | 100% | 36/36 = 100% | [90%, 100%] | 250 ms |

| Binary point | n | Correct at 0.5 | AUC | Brier | ECE |
|---|---|---|---|---|---|
| memory_write | 34 | 31/34 | 0.99 | 0.095 | 0.227 |
| recall | 36 | 36/36 | 1.00 | 0.008 | 0.076 |

## Agreement by confidence band

| Band | n | Agreement |
|---|---|---|
| 0.00-0.40 | 12 | 4/12 = 33% |
| 0.40-0.60 | 8 | 8/8 = 100% |
| 0.60-0.75 | 9 | 9/9 = 100% |
| 0.75-0.90 | 26 | 26/26 = 100% |
| 0.90-1.00 | 15 | 15/15 = 100% |

## Calibration by primitive (declared confidence vs. agreement)

| Primitive | n | Agreement | Mean confidence | ECE |
|---|---|---|---|---|
| truth | 70 | 89% | 0.68 | 0.202 |
