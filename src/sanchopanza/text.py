"""What code can decide, code decides. Cheap deterministic checks that run before any model.

- `truncate`: state sent to a decider is trimmed; more text is more noise, not more signal.
- `quote_present`: a quotation that is not in the source is fabricated. No model call.
- `is_repeat`: two queries that share most tokens are the same query. The model only has
  to catch synonyms.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

STOPWORDS = frozenset(
    [
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "y",
        "o",
        "en",
        "a",
        "con",
        "por",
        "para",
        "un",
        "una",
        "sobre",
        "al",
        "que",
        "se",
        "su",
        "sus",
        "segun",
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "with",
        "by",
        "from",
        "at",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
    ]
)
JACCARD_REPEAT = 0.7


def truncate(text: object, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + " [...]"


def normalize(text: str) -> str:
    """Collapse whitespace and straighten typographic quotes: the only tolerated edits."""
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))


def quote_present(quote: str, source: str) -> bool:
    quote_n, source_n = normalize(quote), normalize(source)
    return bool(quote_n) and quote_n.lower() in source_n.lower()


def tokens(text: str) -> frozenset[str]:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return frozenset(t for t in re.findall(r"[a-z0-9/-]+", plain) if t not in STOPWORDS)


def is_repeat(query: str, previous: Iterable[str], *, threshold: float = JACCARD_REPEAT) -> bool:
    """True when the query shares almost all its tokens with an earlier one."""
    current = tokens(query)
    if not current:
        return False
    for earlier in previous:
        other = tokens(earlier)
        if other and len(current & other) / len(current | other) >= threshold:
            return True
    return False
