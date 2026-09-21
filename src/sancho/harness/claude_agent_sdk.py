"""Hooks for the Claude Agent SDK (and Claude Code, which shares the protocol).

    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
    from sancho.harness.claude_agent_sdk import pre_tool_use, post_tool_use

    options = ClaudeAgentOptions(hooks={
        "PreToolUse": [HookMatcher(matcher="Agent|WebSearch|Bash", hooks=[pre_tool_use(guardian)])],
        "PostToolUse": [HookMatcher(matcher="Agent", hooks=[post_tool_use(guardian)])],
    })

Hook input: {"hook_event_name", "tool_name", "tool_input", "tool_response"?}.
Hook output: {"hookSpecificOutput": {"hookEventName", "permissionDecision", ...}}.
This module imports nothing from the SDK, so it is testable without it; `hook_matchers`
builds the matcher objects when the SDK is installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .generic import Guardian, ToolCall, Verdict

Hook = Callable[..., Any]


def to_hook_output(event: str, verdict: Verdict) -> dict[str, Any]:
    if verdict.action == "allow":
        return {}
    if verdict.action == "deny":
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": verdict.reason,
            }
        }
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "allow",
            "permissionDecisionReason": verdict.reason,
            "updatedInput": dict(verdict.arguments or {}),
        }
    }


def pre_tool_use(guardian: Guardian) -> Hook:
    async def hook(input_data: dict[str, Any], _tool_use_id: Any = None, _context: Any = None):
        event = str(input_data.get("hook_event_name", "PreToolUse"))
        call = ToolCall(
            name=str(input_data.get("tool_name", "")),
            arguments=dict(input_data.get("tool_input") or {}),
            event=event,
        )
        return to_hook_output(event, await guardian.before_tool(call))

    return hook


def post_tool_use(guardian: Guardian) -> Hook:
    async def hook(input_data: dict[str, Any], _tool_use_id: Any = None, _context: Any = None):
        event = str(input_data.get("hook_event_name", "PostToolUse"))
        call = ToolCall(
            name=str(input_data.get("tool_name", "")),
            arguments=dict(input_data.get("tool_input") or {}),
            event=event,
        )
        note = await guardian.after_tool(call, input_data.get("tool_response"))
        if not note:
            return {}
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": note}}

    return hook


def hook_matchers(guardian: Guardian) -> dict[str, list[Any]]:
    """The `hooks=` mapping for `ClaudeAgentOptions`. Requires the SDK to be installed."""
    from claude_agent_sdk import HookMatcher

    c = guardian.config
    pre = "|".join(sorted(c.delegate_tools | c.search_tools | c.shell_tools))
    post = "|".join(sorted(c.delegate_tools))
    return {
        "PreToolUse": [HookMatcher(matcher=pre, hooks=[pre_tool_use(guardian)])],
        "PostToolUse": [HookMatcher(matcher=post, hooks=[post_tool_use(guardian)])],
    }
