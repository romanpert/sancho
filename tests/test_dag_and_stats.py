"""The DAG is built by code, and the statistics are recomputable without libraries."""

from __future__ import annotations

import pytest

from sanchopanza.dag import build_dag, transitive_closure, transitive_reduction, waves
from sanchopanza.eval import stats


def test_the_dag_breaks_cycles_by_probability_and_removes_transitives():
    nodes = ["A", "B", "C", "D"]
    pairs = {
        ("A", "B"): 0.9,
        ("B", "C"): 0.9,
        ("A", "C"): 0.7,  # transitive: redundant
        ("C", "B"): 0.6,  # two-cycle with B->C: loses
        ("C", "D"): 0.8,
        ("D", "A"): 0.55,  # closes a long cycle: weakest, dropped
        ("B", "D"): 0.3,  # below threshold
    }
    edges = build_dag(nodes, pairs)
    assert edges == {("A", "B"), ("B", "C"), ("C", "D")}
    assert waves(nodes, edges) == [["A"], ["B"], ["C"], ["D"]]
    assert waves(["X", "Y", "Z"], {("X", "Z"), ("Y", "Z")}) == [["X", "Y"], ["Z"]]
    assert transitive_reduction({("A", "B"), ("B", "C"), ("A", "C")}) == {("A", "B"), ("B", "C")}
    assert ("A", "C") in transitive_closure(nodes, edges)


def test_wilson_is_not_wald():
    p, low, high = stats.wilson(18, 20)
    assert p == 0.9 and 0.69 < low < 0.71 and 0.97 < high < 0.98
    assert stats.wilson(0, 0) == (0.0, 0.0, 0.0)


def test_mcnemar_and_bootstrap_on_identical_series_are_null():
    a = [True, True, False, True]
    assert stats.mcnemar(a, a) == (0, 0, 1.0)
    observed, low, high = stats.bootstrap_difference(a, a)
    assert observed == 0.0 and low == 0.0 and high == 0.0


def test_auc_brier_ece_sanity():
    scores = [0.9, 0.8, 0.2, 0.1]
    truths = [True, True, False, False]
    assert stats.auc(scores, truths) == 1.0
    assert stats.brier(scores, truths) == pytest.approx(0.025)
    assert stats.ece([1.0, 1.0, 0.0, 0.0], truths) == 0.0
    assert stats.ece([0.5, 0.5], [True, True]) == pytest.approx(0.5)
    assert stats.cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0
    assert stats.median([3, 1, 2]) == 2 and stats.median([1, 2, 3, 4]) == 2.5


def test_excerpt_leaves_short_text_alone_and_finds_the_window_in_long_text():
    """The bug the end-to-end benchmark found: a head-only cut hides the answer."""
    from sanchopanza.text import excerpt

    corto = "una pagina corta que cabe entera"
    assert excerpt(corto, "cualquier proposito", 1500) == corto

    relleno = "preamble about licensing and acknowledgements. " * 40
    enterrado = "the reconstructed DAG reaches precision 100 % and recall 88 % here."
    largo = relleno + enterrado + relleno
    trozo = excerpt(largo, "precision and recall of the reconstructed DAG", 600)

    assert enterrado in trozo, "la ventana tiene que traer la parte que responde al proposito"
    assert trozo.startswith(relleno[:50]), "y tiene que conservar la cabecera"
    assert " [...] " in trozo
    assert len(trozo) <= 600 + len(" [...] ")

    # Sin palabras utiles en el proposito, cae a cabeza mas cola y no revienta.
    assert " [...] " in excerpt(largo, "de la", 600)
