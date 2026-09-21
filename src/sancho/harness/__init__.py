"""Adapters between the squire and agent harnesses.

`generic.Guardian` is the harness-agnostic layer: a tool call comes in, a verdict (allow,
deny with reason, rewrite arguments) comes out; a tool result comes in, an optional note
for the orchestrator comes out. Every concrete adapter is a thin translation of that:

- `claude_agent_sdk`: PreToolUse / PostToolUse hook functions for the Claude Agent SDK.
- `claude_code`: the same, as a command-line hook reading JSON on stdin (Claude Code, and
  any harness with the same hook protocol).
- `mcp`: the decision points the agent asks for on purpose, as MCP tools.
- `openai_agents`: a tool guardrail function in the shape the OpenAI Agents SDK expects.
"""

from .generic import Guardian, HarnessConfig, ToolCall, Verdict

__all__ = ["Guardian", "HarnessConfig", "ToolCall", "Verdict"]
