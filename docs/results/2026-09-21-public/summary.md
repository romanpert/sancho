# Public benches, Jev 1.13.0, 2026-09-21

Cases: 245 - decision calls: 227 - input tokens: 184594 - cost: 0.0078 USD

| Point | n | Coverage | Agreement when deciding | Wilson 95 % | Median latency |
|---|---|---|---|---|---|
| citation | 20 | 90% | 18/18 = 100% | [82%, 100%] | 288 ms |
| command | 32 | 47% | 15/15 = 100% | [80%, 100%] | 0 ms |
| dependency | 20 | 100% | 19/20 = 95% | [76%, 99%] | 546 ms |
| entity | 24 | 100% | 24/24 = 100% | [86%, 100%] | 250 ms |
| facts | 20 | 75% | 14/15 = 93% | [70%, 99%] | 250 ms |
| injection | 28 | 100% | 28/28 = 100% | [88%, 100%] | 265 ms |
| numeric_citation | 24 | 92% | 22/22 = 100% | [85%, 100%] | 250 ms |
| routing | 20 | 100% | 14/20 = 70% | [48%, 85%] | 274 ms |
| search | 18 | 100% | 17/18 = 94% | [74%, 99%] | 258 ms |
| triage | 16 | 100% | 14/16 = 88% | [64%, 97%] | 266 ms |
| unsourced | 22 | 100% | 21/22 = 95% | [78%, 99%] | 266 ms |

| Binary point | n | Correct at 0.5 | AUC | Brier | ECE |
|---|---|---|---|---|---|
| command | 15 | 15/15 | nan | 0.005 | 0.058 |
| dependency | 20 | 19/20 | 1.00 | 0.040 | 0.148 |
| entity | 24 | 24/24 | 1.00 | 0.005 | 0.060 |
| injection | 28 | 28/28 | 1.00 | 0.007 | 0.037 |
| unsourced | 22 | 21/22 | 1.00 | 0.030 | 0.083 |

`command`: the code deny-list fired on 17 cases, 17 of them labelled dangerous; code or model together: 32/32 correct.

## Agreement by confidence band

| Band | n | Agreement |
|---|---|---|
| 0.00-0.40 | 8 | 4/8 = 50% |
| 0.40-0.60 | 6 | 1/6 = 17% |
| 0.60-0.75 | 10 | 9/10 = 90% |
| 0.75-0.90 | 52 | 51/52 = 98% |
| 0.90-1.00 | 142 | 141/142 = 99% |

## Calibration by primitive (declared confidence vs. agreement)

| Primitive | n | Agreement | Mean confidence | ECE |
|---|---|---|---|---|
| choice | 55 | 98% | 0.96 | 0.026 |
| score | 20 | 70% | 0.72 | 0.209 |
| truth | 143 | 97% | 0.87 | 0.106 |

## Plan `plan-register`: 56 ordered pairs, 9 reference edges

- Raw (p >= 0.5): 20 edges, precision 40%, recall 89%, AUC 0.93; waves [['L1', 'L2'], ['L3', 'L4'], ['L5', 'L6', 'L7', 'L8']]
- After dag.py: 7 edges, precision 100%, recall 88% (closure 100% / 95%); waves [['L1', 'L2'], ['L3', 'L4'], ['L5'], ['L6'], ['L7'], ['L8']]; missing [('L2', 'L8')]
- Reference waves: [['L1', 'L2'], ['L3', 'L4'], ['L5'], ['L6'], ['L7'], ['L8']]
