"""Tool selection as a LangChain / LangGraph / deepagents `AgentMiddleware`.

    from sanchopanza.harness.langchain import ToolSelectMiddleware

    middleware = [ToolSelectMiddleware(squire, always={"web_search"})]
    agent = create_agent(model, tools, middleware=middleware)

On every model call the tools on the request are grouped (`group_of`: the tool's
`metadata["server"]`, else the name's prefix before the first `_`, else the name), the squire
is asked which groups the current purpose needs, and the request continues with only those
groups' tools. The purpose is the last human message in the request.

Anything unexpected leaves the request untouched: no tools, a tool without a name, a single
group, no human message, a provider outage, an exception. The middleware can only narrow the
call, never break it, and the squire journals every selection with its probabilities.

Imports nothing from LangChain at module level. With `langchain` installed the class is a
real `AgentMiddleware`; without it, a plain object with the same methods, which is how the
tests drive it. Tested in shape (a request-like object), not against a live agent loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..squire import Squire
from ..text import truncate

GroupOf = Callable[[Any], str]
NAMES_IN_ABOUT = 6


def _base() -> type:
    try:
        from langchain.agents.middleware.types import AgentMiddleware
    except ImportError:  # the adapter must import and be testable without LangChain
        return object
    return AgentMiddleware


def default_group_of(tool: Any) -> str:
    """The server an MCP tool came from, else the prefix of its name."""
    metadata = getattr(tool, "metadata", None) or {}
    server = metadata.get("server") if isinstance(metadata, Mapping) else None
    if server:
        return str(server)
    name = str(getattr(tool, "name", "") or "")
    return name.split("_", 1)[0] if "_" in name else name


def catalog_of(
    tools: Iterable[Any], group_of: GroupOf
) -> tuple[list[dict[str, Any]], dict[str, list[Any]]]:
    """Group tools into a catalog the squire can read, in a stable order."""
    groups: dict[str, list[Any]] = {}
    for tool in tools:
        groups.setdefault(group_of(tool), []).append(tool)
    catalog: list[dict[str, Any]] = []
    for name in sorted(groups):
        members = groups[name]
        names = ", ".join(sorted(str(getattr(t, "name", "")) for t in members)[:NAMES_IN_ABOUT])
        first = str(getattr(members[0], "description", "") or "")
        catalog.append(
            {
                "name": name,
                "about": truncate(f"{len(members)} tools ({names}). {first}", 160),
            }
        )
    return catalog, groups


def last_human_text(messages: Iterable[Any]) -> str:
    """The latest human message as plain text, or an empty string."""
    for message in reversed(list(messages)):
        kind = str(getattr(message, "type", "") or "")
        if kind != "human" and not message.__class__.__name__.endswith("HumanMessage"):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                str(block.get("text", "")) for block in content if isinstance(block, Mapping)
            )
        return str(content)
    return ""


class ToolSelectMiddleware(_base()):  # type: ignore[misc]
    """Narrow `request.tools` to the groups the squire says this purpose needs."""

    def __init__(
        self,
        squire: Squire,
        *,
        always: Iterable[str] = (),
        group_of: GroupOf = default_group_of,
        clues_of: Callable[[Any], str] | None = None,
    ) -> None:
        if _base() is not object:
            super().__init__()
        self._squire = squire
        self._always = frozenset(always)
        self._group_of = group_of
        self._clues_of = clues_of

    async def narrow(self, request: Any) -> Any:
        """The request with fewer tools, or the same request when nothing should change."""
        try:
            tools = list(getattr(request, "tools", None) or [])
            if not tools or any(not getattr(t, "name", None) for t in tools):
                return request
            catalog, groups = catalog_of(tools, self._group_of)
            if len(catalog) < 2:
                return request
            purpose = last_human_text(getattr(request, "messages", None) or [])
            if not purpose.strip():
                return request
            clues = self._clues_of(request) if self._clues_of else ""
            selection = await self._squire.select_tools(
                purpose=purpose, catalog=catalog, clues=clues, always=self._always
            )
            if not selection.narrowed:
                return request
            # By identity: tool objects (pydantic models, dataclasses) need not be hashable.
            keep = {id(t) for name in selection.keep for t in groups.get(name, ())}
            override = getattr(request, "override", None)
            if override is None:
                return request
            return override(tools=[t for t in tools if id(t) in keep])
        except Exception:  # never break the model call
            return request

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        return await handler(await self.narrow(request))

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        """Sync path: narrows only when no event loop is running; otherwise passes through."""
        try:
            narrowed = asyncio.run(self.narrow(request))
        except RuntimeError:  # a loop is already running: the async path is the one in use
            narrowed = request
        return handler(narrowed)


__all__ = ["ToolSelectMiddleware", "catalog_of", "default_group_of", "last_human_text"]
