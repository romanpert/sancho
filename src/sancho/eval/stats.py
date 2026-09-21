"""Minimal statistics for the benches, in plain Python: no numpy, no scipy.

Everything the paper reports comes from here, so anyone can recompute it from the result
JSON without installing anything.

- `wilson`: 95 % interval of a proportion (Wilson, not Wald: with n < 30 Wald lies).
- `bootstrap_difference`: CI of the accuracy difference between two systems on the same
  cases (paired resampling, 2000 replicas, fixed seed).
- `mcnemar`: exact (binomial) test for two systems on the same cases.
- `cohen_kappa`: agreement between two labellers beyond chance.
- `brier` and `ece`: calibration of a probability against binary labels.
- `auc`: area under the ROC curve by the Mann-Whitney statistic.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Proportion and its 95 % Wilson interval: (p, low, high)."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p = hits / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return p, max(0.0, centre - margin), min(1.0, centre + margin)


def bootstrap_difference(
    a: Sequence[bool], b: Sequence[bool], *, replicas: int = 2000, seed: int = 7
) -> tuple[float, float, float]:
    """Accuracy difference (a - b) with a 95 % CI by paired resampling."""
    if len(a) != len(b) or not a:
        raise ValueError("both series must have the same non-zero length")
    n = len(a)
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(replicas):
        idx = [rng.randrange(n) for _ in range(n)]
        diffs.append((sum(a[i] for i in idx) - sum(b[i] for i in idx)) / n)
    diffs.sort()
    observed = (sum(a) - sum(b)) / n
    return observed, diffs[int(0.025 * replicas)], diffs[int(0.975 * replicas) - 1]


def mcnemar(a: Sequence[bool], b: Sequence[bool]) -> tuple[int, int, float]:
    """Discordant counts (a right and b wrong; b right and a wrong) and exact two-sided p."""
    only_a = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    only_b = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    n = only_a + only_b
    if n == 0:
        return 0, 0, 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return only_a, only_b, min(1.0, 2 * tail)


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("both series must have the same non-zero length")
    n = len(a)
    labels = sorted(set(a) | set(b))
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    expected = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def brier(probabilities: Sequence[float], truths: Sequence[bool]) -> float:
    """Mean of (p - y)^2. Lower is better; 0.25 is a coin flip."""
    pairs = list(zip(probabilities, truths, strict=True))
    return sum((p - (1.0 if y else 0.0)) ** 2 for p, y in pairs) / len(pairs)


def ece(probabilities: Sequence[float], truths: Sequence[bool], *, bins: int = 5) -> float:
    """Expected calibration error with equal-width bins. Few cases: wide bins."""
    pairs = list(zip(probabilities, truths, strict=True))
    total = len(pairs)
    error = 0.0
    for b in range(bins):
        low, high = b / bins, (b + 1) / bins
        inside = [(p, y) for p, y in pairs if low <= p < high or (b == bins - 1 and p == 1.0)]
        if not inside:
            continue
        mean_conf = sum(p for p, _ in inside) / len(inside)
        accuracy = sum(1 for _, y in inside if y) / len(inside)
        error += len(inside) / total * abs(mean_conf - accuracy)
    return error


def auc(scores: Sequence[float], truths: Sequence[bool]) -> float:
    """AUC-ROC by Mann-Whitney: probability that a positive scores above a negative."""
    positives = [s for s, y in zip(scores, truths, strict=True) if y]
    negatives = [s for s, y in zip(scores, truths, strict=True) if not y]
    if not positives or not negatives:
        return float("nan")
    total = 0.0
    for p in positives:
        for q in negatives:
            total += 1.0 if p > q else (0.5 if p == q else 0.0)
    return total / (len(positives) * len(negatives))


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2
