"""The harness-agnostic layer: tool calls in, verdicts out.

A `Guardian` watches three families of tools:

- **delegation** (`Agent`, `Task`, ...): rewrites the requested tier to the one the squire
  chose (model per subtask) and, after the subtask returns, appends a review note.
- **search** (`WebSearch`, ...): denies a repeated query, or points to a cheaper engine.
- **shell** (`Bash`, ...): denies with a reason when the code list or the squire flags it.

Everything else passes untouched. Denying never breaks the agent: it receives the reason
and changes course.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from ..points.routing import TIERS, Tier
from ..squire import Squire

Action = Literal["allow", "deny", "rewrite"]


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    event: str = "PreToolUse"


@dataclass(frozen=True, slots=True)
class Verdict:
    action: Action
    reason: str = ""
    arguments: Mapping[str, Any] | None = None

    @property
    def allowed(self) -> bool:
        return self.action != "deny"


ALLOW = Verdict("allow")


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    """Names the harness uses. Defaults match Claude Code and the Claude Agent SDK."""

    delegate_tools: frozenset[str] = frozenset({"Agent", "Task"})
    delegate_task_keys: tuple[str, ...] = ("prompt", "description")
    delegate_tier_key: str = "subagent_type"
    # tier -> the subagent/model name the harness understands. Empty: the tier names.
    tiers: Mapping[Tier, str] = field(default_factory=dict)
    review_delegations: bool = True
    search_tools: frozenset[str] = frozenset({"WebSearch"})
    search_query_key: str = "query"
    # **Probe the capability; do not declare it.** This callable decides whether the squire
    # is allowed to route a query away from the model's own search, so it answers "does that
    # alternative exist and work, right now". A constant `True`, or a function that answers a
    # different question (is there quota left, is the feature flag on), sends work into a
    # hole: the routing succeeds, nothing fails, fail-open never fires, and the job comes
    # back empty and cheap. That has happened in production, and the arm that produced
    # nothing was 75 % cheaper. See docs/where-it-pays.md, section 5.
    cheap_search_available: Callable[[], bool] = lambda: False
    cheap_search_hint: str = (
        "Use the cheap search tool for this query; keep the model's search for what it cannot find."
    )
    shell_tools: frozenset[str] = frozenset({"Bash", "bash", "shell", "run_command", "execute"})
    shell_command_key: str = "command"
    guard_environment: Mapping[str, Any] | None = None
    result_limit: int = 4000

    def tier_name(self, tier: Tier) -> str:
        return self.tiers.get(tier, tier)

    def tier_of(self, name: str | None) -> Tier | None:
        if name in TIERS:
            return name  # type: ignore[return-value]
        for tier, mapped in self.tiers.items():
            if mapped == name:
                return tier
        return None


class Guardian:
    def __init__(self, squire: Squire, config: HarnessConfig | None = None) -> None:
        self.squire = squire
        self.config = config or HarnessConfig()

    async def before_tool(self, call: ToolCall) -> Verdict:
        c = self.config
        if call.name in c.delegate_tools:
            return await self._before_delegate(call)
        if call.name in c.search_tools:
            return await self._before_search(call)
        if call.name in c.shell_tools:
            return await self._before_shell(call)
        return ALLOW

    async def after_tool(self, call: ToolCall, response: Any) -> str | None:
        """A note for the orchestrator after a delegated subtask returns, or None."""
        c = self.config
        if call.name not in c.delegate_tools or not c.review_delegations:
            return None
        task = self._task_text(call.arguments)
        text = text_of(response)
        if not task.strip() or not text.strip():
            return None
        outcome = await self.squire.review_report(task, text[: c.result_limit])
        return outcome.message if outcome else None

    # --- families --------------------------------------------------------------------

    async def _before_delegate(self, call: ToolCall) -> Verdict:
        c = self.config
        task = self._task_text(call.arguments)
        if not task.strip():
            return ALLOW
        requested = call.arguments.get(c.delegate_tier_key)
        default = c.tier_of(requested if isinstance(requested, str) else None) or "default"
        result = await self.squire.route_task(task, requested=requested, default=default)
        chosen = c.tier_name(result.tier)
        if chosen == requested or (requested is None and result.tier == default):
            return ALLOW
        return Verdict(
            "rewrite", result.reason, {**dict(call.arguments), c.delegate_tier_key: chosen}
        )

    async def _before_search(self, call: ToolCall) -> Verdict:
        c = self.config
        query = str(call.arguments.get(c.search_query_key) or "")
        if not query.strip():
            return ALLOW
        route = await self.squire.route_search(query, cheap_available=c.cheap_search_available())
        if route.route == "cut":
            return Verdict(
                "deny",
                "This query repeats one already made in this job. Do not rephrase it: use the "
                "results you have or change the angle.",
            )
        if route.route == "cheap":
            return Verdict("deny", f"{c.cheap_search_hint} (category '{route.category}').")
        return ALLOW

    async def _before_shell(self, call: ToolCall) -> Verdict:
        c = self.config
        command = str(call.arguments.get(c.shell_command_key) or "")
        if not command.strip():
            return ALLOW
        result = await self.squire.guard_command(command, environment=c.guard_environment)
        if not result.denied:
            return ALLOW
        return Verdict(
            "deny",
            f"Command denied ({result.reason}). This job does not delete outside its output, "
            "does not send files or secrets to the network, does not change permissions and "
            "does not execute downloaded content. Achieve the same with the job's own tools.",
        )

    def _task_text(self, arguments: Mapping[str, Any]) -> str:
        for key in self.config.delegate_task_keys:
            value = arguments.get(key)
            if value:
                return str(value)
        return ""


def text_of(response: Any) -> str:
    """The text of a tool result, whatever shape it arrives in."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        content = response.get("content")
        if isinstance(content, list):
            return "\n".join(
                str(part.get("text", "")) for part in content if isinstance(part, Mapping)
            )
        return str(content or response.get("text") or "")
    if isinstance(response, list):
        return "\n".join(text_of(part) for part in response)
    return str(response)
