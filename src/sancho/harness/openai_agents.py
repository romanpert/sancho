"""A tool guardrail in the shape the OpenAI Agents SDK (and Codex-style harnesses) expect.

Status: interface adapter, exercised by unit tests against the dict shape, **not** run
against the SDK itself. The SDK's `GuardrailFunctionOutput(output_info, tripwire_triggered)`
maps one-to-one onto the dict returned here. Wrap it like this:

    from agents import GuardrailFunctionOutput, input_guardrail
    check = tool_guardrail(guardian)

    @input_guardrail
    async def sancho_guard(ctx, agent, input):
        result = await check("shell", {"command": str(input)})
        return GuardrailFunctionOutput(result["output_info"], result["tripwire_triggered"])

Delegation rewriting has no equivalent in a guardrail; use `Guardian.before_tool` directly
in a tool wrapper if the harness lets you replace arguments.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from .generic import Guardian, ToolCall

GuardrailFn = Callable[[str, Mapping[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


def tool_guardrail(guardian: Guardian) -> GuardrailFn:
    async def check(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        verdict = await guardian.before_tool(ToolCall(tool_name, dict(arguments)))
        return {
            "tripwire_triggered": verdict.action == "deny",
            "output_info": {
                "action": verdict.action,
                "reason": verdict.reason,
                "arguments": dict(verdict.arguments) if verdict.arguments else None,
            },
        }

    return check
