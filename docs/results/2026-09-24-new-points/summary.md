# New decision points, first run (Jev 1.13)

Cases: 124 - decision calls: 122 - input tokens: 84092 - cost: 0.0035 USD

| Point | n | Coverage | Agreement when deciding | Wilson 95 % | Median latency |
|---|---|---|---|---|---|
| edge | 20 | 85% | 15/17 = 88% | [66%, 97%] | 304 ms |
| extract_gate | 16 | 100% | 15/16 = 94% | [72%, 99%] | 297 ms |
| goal_met | 14 | 100% | 14/14 = 100% | [78%, 100%] | 257 ms |
| memory_collision | 16 | 100% | 14/16 = 88% | [64%, 97%] | 311 ms |
| memory_write | 16 | 100% | 12/16 = 75% | [51%, 90%] | 344 ms |
| recall | 14 | 100% | 14/14 = 100% | [78%, 100%] | 274 ms |
| redundant_page | 16 | 100% | 11/16 = 69% | [44%, 86%] | 282 ms |
| repeats_check | 12 | 100% | 12/12 = 100% | [76%, 100%] | 281 ms |

| Binary point | n | Correct at 0.5 | AUC | Brier | ECE |
|---|---|---|---|---|---|
| extract_gate | 16 | 15/16 | 1.00 | 0.030 | 0.101 |
| goal_met | 14 | 14/14 | 1.00 | 0.037 | 0.131 |
| memory_write | 16 | 16/16 | 1.00 | 0.073 | 0.224 |
| recall | 14 | 14/14 | 1.00 | 0.003 | 0.051 |
| redundant_page | 16 | 15/16 | 1.00 | 0.039 | 0.121 |
| repeats_check | 12 | 12/12 | 1.00 | 0.017 | 0.112 |

## Agreement by confidence band

| Band | n | Agreement |
|---|---|---|
| 0.00-0.40 | 11 | 6/11 = 55% |
| 0.40-0.60 | 7 | 4/7 = 57% |
| 0.60-0.75 | 9 | 5/9 = 56% |
| 0.75-0.90 | 31 | 30/31 = 97% |
| 0.90-1.00 | 63 | 62/63 = 98% |

## Calibration by primitive (declared confidence vs. agreement)

| Primitive | n | Agreement | Mean confidence | ECE |
|---|---|---|---|---|
| truth | 121 | 88% | 0.80 | 0.084 |
