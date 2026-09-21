"""Decision providers. Each one is a file that implements `Decider`; nothing else changes.

    create("jev", api_key=...)            TypeSafe Jev over HTTP
    create("recorded", path=...)          replays a fixture; tests and dry runs, free
    create("null")                        answers nothing; every policy uses its default
    create("llm", complete=...)           any LLM forced into a JSON schema
    create("local", handlers=...)         your own classifiers, embeddings, vision models
    FallbackDecider([a, b])               first provider that answers wins
    RoutedDecider({"routing": a}, b)      one provider per decision point

Third-party packages register more under the `sancho.providers` entry-point group.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from ..contract import Decider
from .chain import FallbackDecider, RoutedDecider
from .fixed import FixedDecider
from .local import LocalDecider
from .null import NullDecider
from .recorded import RecordedDecider, RecordingDecider, key_of

__all__ = [
    "FallbackDecider",
    "FixedDecider",
    "LocalDecider",
    "NullDecider",
    "RecordedDecider",
    "RecordingDecider",
    "RoutedDecider",
    "create",
    "key_of",
]

_BUILTIN = {
    "null": "sancho.providers.null:NullDecider",
    "recorded": "sancho.providers.recorded:RecordedDecider",
    "jev": "sancho.providers.jev:JevDecider",
    "llm": "sancho.providers.llm:LLMDecider",
    "local": "sancho.providers.local:LocalDecider",
}


def _load(target: str) -> type:
    module_name, _, attr = target.partition(":")
    module = __import__(module_name, fromlist=[attr])
    return getattr(module, attr)


def available() -> dict[str, str]:
    """Provider names and where they come from, built-ins plus installed entry points."""
    found = dict(_BUILTIN)
    for ep in entry_points(group="sancho.providers"):
        found.setdefault(ep.name, ep.value)
    return found


def create(name: str, **kwargs: Any) -> Decider:
    """Instantiate a provider by name. Import errors surface as-is: missing extras are loud."""
    targets = available()
    if name not in targets:
        raise KeyError(f"unknown provider {name!r}; known: {sorted(targets)}")
    cls = _load(targets[name])
    if name == "recorded" and "path" in kwargs:
        return cls.from_file(kwargs["path"])
    return cls(**kwargs)
