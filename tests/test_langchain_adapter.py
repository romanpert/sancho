"""The LangChain middleware narrows the tools of a request and never breaks the call."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any

from sanchopanza.harness.langchain import (
    ToolSelectMiddleware,
    catalog_of,
    default_group_of,
    last_human_text,
)
from sanchopanza.providers import FixedDecider, NullDecider

from .helpers import squire, yes


@dataclass(frozen=True)
class Tool:
    name: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Human:
    content: Any
    type: str = "human"


@dataclass(frozen=True)
class AI:
    content: str
    type: str = "ai"


@dataclass(frozen=True)
class Request:
    tools: list[Any]
    messages: list[Any]

    def override(self, **changes: Any) -> Request:
        return replace(self, **changes)


TOOLS = [
    Tool("aemps_buscar", "Search Spanish medicines"),
    Tool("aemps_ficha", "Fetch an SmPC"),
    Tool("chembl_search", "Bioactivity search"),
    Tool("web_search", "General web search", {"server": "web"}),
]
MESSAGES = [AI("hola"), Human("¿interacción entre Sintrom e ibuprofeno?")]


def _handler_capturing(seen: list[Any]):
    async def handler(request: Any) -> str:
        seen.append(request)
        return "ok"

    return handler


def _run(middleware: ToolSelectMiddleware, request: Request) -> Request:
    seen: list[Any] = []
    asyncio.run(middleware.awrap_model_call(request, _handler_capturing(seen)))
    return seen[0]


def test_groups_come_from_metadata_server_then_name_prefix():
    assert default_group_of(Tool("web_search", metadata={"server": "web"})) == "web"
    assert default_group_of(Tool("aemps_buscar")) == "aemps"
    assert default_group_of(Tool("bare")) == "bare"
    catalog, groups = catalog_of(TOOLS, default_group_of)
    assert [g["name"] for g in catalog] == ["aemps", "chembl", "web"]
    assert catalog[0]["about"].startswith("2 tools (aemps_buscar, aemps_ficha)")
    assert [t.name for t in groups["aemps"]] == ["aemps_buscar", "aemps_ficha"]


def test_the_purpose_is_the_last_human_message_even_as_content_blocks():
    assert last_human_text(MESSAGES) == "¿interacción entre Sintrom e ibuprofeno?"
    blocks = [Human([{"type": "text", "text": "dosis"}, {"type": "text", "text": "pediátrica"}])]
    assert last_human_text(blocks) == "dosis pediátrica"
    assert last_human_text([AI("solo asistente")]) == ""


def test_the_request_goes_on_with_only_the_needed_groups_and_the_pinned_one():
    # catalog order is aemps, chembl, web -> needed_0, needed_1, needed_2
    decider = FixedDecider({"needed_0": yes(0.9), "needed_1": yes(0.05), "needed_2": yes(0.1)})
    sq, _ = squire(decider)
    seen = _run(ToolSelectMiddleware(sq, always={"web"}), Request(TOOLS, MESSAGES))
    assert [t.name for t in seen.tools] == ["aemps_buscar", "aemps_ficha", "web_search"]
    assert seen.messages == MESSAGES and decider.calls == 1


def test_nothing_changes_when_there_is_nothing_to_decide():
    decider = FixedDecider({"needed_0": yes(0.9), "needed_1": yes(0.0)})
    sq, _ = squire(decider)
    mw = ToolSelectMiddleware(sq)
    no_tools = Request([], MESSAGES)
    assert _run(mw, no_tools) is no_tools
    one_group = Request(TOOLS[:2], MESSAGES)
    assert _run(mw, one_group) is one_group
    no_human = Request(TOOLS, [AI("x")])
    assert _run(mw, no_human) is no_human
    unnamed = Request([*TOOLS, Tool("")], MESSAGES)
    assert _run(mw, unnamed) is unnamed
    assert decider.calls == 0


def test_a_silent_decider_leaves_the_full_catalog():
    sq, _ = squire(NullDecider())
    request = Request(TOOLS, MESSAGES)
    assert _run(ToolSelectMiddleware(sq), request) is request


def test_a_request_without_override_is_passed_through():
    @dataclass(frozen=True)
    class Bare:
        tools: list[Any]
        messages: list[Any]

    sq, _ = squire(FixedDecider({"needed_0": yes(0.9), "needed_1": yes(0.0), "needed_2": yes(0.0)}))
    request = Bare(TOOLS, MESSAGES)
    assert _run(ToolSelectMiddleware(sq), request) is request


def test_the_sync_path_narrows_outside_an_event_loop():
    sq, _ = squire(FixedDecider({"needed_0": yes(0.9), "needed_1": yes(0.0), "needed_2": yes(0.0)}))
    seen: list[Any] = []
    ToolSelectMiddleware(sq).wrap_model_call(Request(TOOLS, MESSAGES), lambda r: seen.append(r))
    assert [t.name for t in seen[0].tools] == ["aemps_buscar", "aemps_ficha"]
