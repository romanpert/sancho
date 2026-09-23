"""Page triage: does a fetched page deserve a place in the large model's context?

Measured (paper, D3): 14/16; both misses at low confidence, one kept on purpose. This is the
largest saving lever the evidence points to (tokens explain 80 % of performance variance in
multi-agent research systems), and the one with the cheapest error: a dropped page costs
coverage, a kept one costs tokens. Hence the asymmetry: in doubt, the page enters.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..contract import Choice, Decision, Question, Truth
from ..policy import Thresholds, probability
from ..text import truncate
from . import injection

TEXT_LIMIT = 1500

SOURCE_KINDS: dict[str, dict[str, Any]] = {
    "official_records": {
        "what": "Government, court, registry, regulator or official statistics portals",
        "examples": ["court rulings", "official gazette", "company registry", "decrees"],
    },
    "news": {
        "what": "Newspapers, wire services, broadcast and digital news outlets",
        "not_for": "press releases hosted by the organization itself",
    },
    "academic": {"what": "Peer-reviewed papers, theses, working papers, scientific databases"},
    "corporate": {"what": "The organization's own site, filings, press releases, product pages"},
    "social": {"what": "Social networks, forums, blogs, video platforms, personal posts"},
    "data_api": {
        "what": "Structured datasets, catalogs and APIs meant to be queried programmatically",
        "examples": ["seismic catalogs", "open data portals", "statistical APIs"],
    },
    "other": {"what": "None of the above, or impossible to tell"},
}


def questions(
    *, purpose: str, title: str = "", url: str = "", text: str
) -> tuple[Mapping[str, Any], dict[str, Question]]:
    state = {
        "purpose": truncate(purpose, 400),
        "title": truncate(title, 200),
        "url": truncate(url, 300),
        "text": truncate(text, TEXT_LIMIT),
    }
    qs: dict[str, Question] = {
        "relevant": Truth("Does `text` address what `purpose` is looking for?"),
        "evidence": Truth(
            "Does `text` contain concrete, citable facts about `purpose` (dates, names, "
            "figures, document references), not just passing mentions?"
        ),
        "injection": injection.question(),
        "source_kind": Choice("Which kind of source is this page?", SOURCE_KINDS),
    }
    return state, qs


@dataclass(frozen=True, slots=True)
class Triage:
    keep: bool
    reason: str
    relevance: float
    evidence: float
    injection: float
    source_kind: str


def decide(decision: Decision, t: Thresholds) -> Triage:
    """Whether a page enters the context. In doubt it enters: cutting costs coverage."""
    if decision.failed:
        return Triage(True, "decider unavailable", 0.0, 0.0, 0.0, "other")
    inj = probability(decision.answer("injection"))
    relevance = decision.answer("relevant").truth
    evidence = probability(decision.answer("evidence"))
    kind = decision.answer("source_kind").choice or "other"
    if inj > t.injection:
        return Triage(False, f"instruction injection ({inj:.2f})", 0.0, 0.0, inj, kind)
    if relevance is None:
        return Triage(True, "no relevance data", 0.0, evidence, inj, kind)
    if relevance < t.relevance:
        return Triage(False, f"not relevant ({relevance:.2f})", relevance, evidence, inj, kind)
    return Triage(True, f"relevant ({relevance:.2f})", relevance, evidence, inj, kind)
