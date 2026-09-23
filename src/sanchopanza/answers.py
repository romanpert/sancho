"""Factories that turn raw model outputs into contract `Answer`s. Any provider can use them.

A local classifier gives a probability; a vision model gives a softmax over labels; an LLM
gives a label and a self-reported confidence. These helpers make each of them a proper
`Answer` with the confidence convention the policies expect.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .contract import Answer, truth_confidence


def truth(probability: float) -> Answer:
    """A yes/no from a probability in [0, 1]. Confidence is 1 at the extremes, 0 at 0.5."""
    p = min(1.0, max(0.0, float(probability)))
    return Answer(kind="truth", truth=p, confidence=truth_confidence(p))


def choice(probabilities: Mapping[str, float], *, confidence: float | None = None) -> Answer:
    """One option from a distribution. Confidence defaults to the top probability minus
    the runner-up, which is what separates a clear pick from a coin flip."""
    if not probabilities:
        return Answer(kind="choice", confidence=0.0)
    total = sum(probabilities.values()) or 1.0
    dist = {k: float(v) / total for k, v in probabilities.items()}
    ordered = sorted(dist.items(), key=lambda kv: kv[1], reverse=True)
    top, runner = ordered[0][1], (ordered[1][1] if len(ordered) > 1 else 0.0)
    return Answer(
        kind="choice",
        choice=ordered[0][0],
        confidence=float(confidence) if confidence is not None else top - runner,
        probabilities=dist,
    )


def score(probabilities: Sequence[float], *, confidence: float | None = None) -> Answer:
    """A scale position from a distribution over levels 0..n-1: the probability-weighted
    mean, as TypeSafe's Score does. Confidence defaults to the mass on the modal level."""
    if not probabilities:
        return Answer(kind="score", confidence=0.0)
    total = sum(probabilities) or 1.0
    dist = [float(p) / total for p in probabilities]
    mean = sum(i * p for i, p in enumerate(dist))
    return Answer(
        kind="score",
        score=mean,
        confidence=float(confidence) if confidence is not None else max(dist),
        probabilities={str(i): p for i, p in enumerate(dist)},
    )


def labelled(label: str, options: Sequence[str], *, confidence: float) -> Answer:
    """A hard label with a self-reported confidence (what an LLM forced into a schema
    gives). The distribution puts `confidence` on the label and spreads the rest."""
    others = [o for o in options if o != label]
    rest = (1.0 - confidence) / len(others) if others else 0.0
    dist = {o: rest for o in others}
    dist[label] = confidence
    return Answer(kind="choice", choice=label, confidence=confidence, probabilities=dist)
