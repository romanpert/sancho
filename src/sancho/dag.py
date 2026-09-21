"""From pairwise "B needs A" probabilities to a clean DAG with parallel waves. Pure code.

What the measurement said (docs/paper.md, Section 5.7): asked pair by pair, the decider
recovers 89 % of the dependencies of an 8-line plan, but it also returns the transitive
ones (if B needs A and C needs B, it says C needs A) and, in two pairs, the reverse
direction with near-tied probabilities. Neither is a reading error: the first is literally
true and the second is a tie. Both are fixed in code:

1. **two-cycles**: if A->B and B->A, keep the edge with the higher probability.
2. **long cycles**: remove, in each cycle, the edge with the lowest probability.
3. **transitive reduction**: an edge A->C is redundant if a path A->...->C exists.
4. **waves**: layered topological order (Kahn). Each layer can run in parallel.

The decider reads pairs; the graph is built by code.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

Edge = tuple[str, str]


def _without_two_cycles(edges: Mapping[Edge, float]) -> dict[Edge, float]:
    kept: dict[Edge, float] = {}
    for (a, b), p in edges.items():
        reverse = (b, a)
        if reverse in edges and edges[reverse] > p:
            continue
        if reverse in edges and edges[reverse] == p and reverse in kept:
            continue
        kept[(a, b)] = p
    return kept


def _has_path(edges: Iterable[Edge], origin: str, target: str, *, skip: Edge | None) -> bool:
    outgoing: dict[str, set[str]] = {}
    for a, b in edges:
        if (a, b) == skip:
            continue
        outgoing.setdefault(a, set()).add(b)
    stack, seen = [origin], set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(outgoing.get(node, ()))
    return False


def _break_cycles(edges: Mapping[Edge, float]) -> dict[Edge, float]:
    """Remove, while cycles remain, the weakest edge that closes one."""
    alive = dict(edges)
    while True:
        closers = [
            (p, edge) for edge, p in alive.items() if _has_path(alive, edge[1], edge[0], skip=edge)
        ]
        if not closers:
            return alive
        _, worst = min(closers, key=lambda pair: pair[0])
        alive = {edge: p for edge, p in alive.items() if edge != worst}


def transitive_reduction(edges: Iterable[Edge]) -> set[Edge]:
    """Drop every edge implied by a longer path. Requires a DAG."""
    pool = set(edges)
    return {(a, b) for a, b in pool if not _has_path(pool, a, b, skip=(a, b))}


def build_dag(
    nodes: Sequence[str], edges: Mapping[Edge, float], *, threshold: float = 0.5
) -> set[Edge]:
    """Clean edges from probabilistic pairs: threshold, cycles, transitive reduction."""
    candidates = {
        (a, b): p for (a, b), p in edges.items() if p >= threshold and a in nodes and b in nodes
    }
    return transitive_reduction(_break_cycles(_without_two_cycles(candidates)))


def waves(nodes: Sequence[str], edges: Iterable[Edge]) -> list[list[str]]:
    """Layers of a topological order. Inside a layer, everything can run in parallel."""
    pool = set(edges)
    incoming = {n: 0 for n in nodes}
    for _, b in pool:
        if b in incoming:
            incoming[b] += 1
    remaining = list(nodes)
    layers: list[list[str]] = []
    while remaining:
        free = [n for n in remaining if incoming[n] == 0]
        if not free:
            layers.append(list(remaining))
            break
        layers.append(free)
        remaining = [n for n in remaining if n not in free]
        for n in free:
            for a, b in pool:
                if a == n and b in incoming:
                    incoming[b] -= 1
    return layers


def transitive_closure(nodes: Sequence[str], edges: Iterable[Edge]) -> set[Edge]:
    pool = set(edges)
    return {(a, b) for a in nodes for b in nodes if a != b and _has_path(pool, a, b, skip=None)}
