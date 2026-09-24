# What more thinking buys on a closed-vocabulary judgment

210 cases answered by every arm. Same model, same prompt, same cases; the only difference is `output_config.effort`. Accuracy is agreement with the bench labels, which no arm saw.

| Effort | Correct | Output tokens | Cost | Per judgment | Median latency |
|---|---|---|---|---|---|
| low | 203/210 = 97% | 2,439 | 0.7884 USD | 3719 millionths | 2731 ms |
| medium | 205/210 = 98% | 5,679 | 0.8694 USD | 4101 millionths | 2808 ms |
| high | 206/210 = 98% | 12,754 | 1.0436 USD | 4946 millionths | 3566 ms |
| xhigh | 206/210 = 98% | 18,352 | 1.1863 USD | 5596 millionths | 3786 ms |

## Against `low`

- **medium**: gains 2 decisions, costs 1.10x per judgment, 1.0x the latency
- **high**: gains 3 decisions, costs 1.33x per judgment, 1.3x the latency
- **xhigh**: gains 3 decisions, costs 1.50x per judgment, 1.4x the latency

Cases where the arms do not all agree (4): eg-25, eg-35, gm-50, rd-42

A case whose label depends on how hard the model was asked to think is a case whose label depends on a setting, not on the criteria. Those are the ones to read before believing any of the columns above.
