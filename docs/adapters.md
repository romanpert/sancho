# Attaching Sancho to a harness

Every adapter translates one thing: a tool call into a `Verdict`, and a tool result into an
optional note. The translation lives in `sanchopanza.harness.generic.Guardian`; the files in
`sanchopanza.harness` are the per-harness wire formats.

```python
from sanchopanza.harness import Guardian, HarnessConfig, ToolCall

guardian = Guardian(squire, HarnessConfig(...))
verdict = await guardian.before_tool(ToolCall("Bash", {"command": "rm -rf /"}))
# Verdict(action="deny", reason="Command denied (recursive delete). ...")
note = await guardian.after_tool(ToolCall("Agent", {"prompt": "..."}), tool_result)
# "Thread review (decision model): answered 0.91, exhausted 0.12, unsourced 0.88. it states facts..."
```

`HarnessConfig` names what the harness calls things: which tools delegate (`Agent`, `Task`),
which key carries the subagent tier (`subagent_type`), which tools search (`WebSearch`),
which run a shell (`Bash`, `shell`, `run_command`), and the map from Sancho's three tiers to
the harness's subagent or model names.

## Claude Agent SDK

Status: **tested** (hook input/output shapes; the SDK is not imported by the tests).

```python
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from sanchopanza.harness.claude_agent_sdk import pre_tool_use, post_tool_use, hook_matchers

options = ClaudeAgentOptions(hooks=hook_matchers(guardian))
# or by hand:
options = ClaudeAgentOptions(hooks={
    "PreToolUse": [HookMatcher(matcher="Agent|WebSearch|Bash", hooks=[pre_tool_use(guardian)])],
    "PostToolUse": [HookMatcher(matcher="Agent", hooks=[post_tool_use(guardian)])],
})
```

What the hooks return:

| Verdict | Hook output |
|---|---|
| allow | `{}` |
| deny | `{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": ...}}` |
| rewrite | `{"hookSpecificOutput": {"permissionDecision": "allow", "updatedInput": {...}}}` |
| note | `{"hookSpecificOutput": {"additionalContext": "..."}}` |

The squire lives for the whole job, so the repeated-query memory and the budget hold across
calls. The MCP tools (`verify_citation`, `evaluate_plan`, ...) are added to the same squire
through `create_sdk_mcp_server` in your harness if you want them in-process.

## Claude Code (command hook)

Status: **tested** (stdin JSON to stdout JSON through `handle()`; environment parsing).

`sanchopanza hook` is a process per event. Configuration is by environment variables (see
`examples/claude_code/README.md`). Same output shapes as the SDK. The hook exits 0 and prints
nothing on any internal error: it can never block a tool by failing.

Because each event is a new process, the squire is new each time: no cross-call query
memory, no per-job budget. If that matters, run Sancho as an MCP server instead and let the
agent call the tools, or use the SDK.

## MCP (any client)

Status: **built on FastMCP, exercised through its parsers in tests; not run against a live
client in CI.**

```python
from sanchopanza.harness.mcp import build_server
build_server(squire).run()
```

Tools: `verify_citation`, `evaluate_plan`, `align_entities`, `classify_field`, `triage_text`.
These are the decisions the orchestrator asks for on purpose. Hooks cover the ones it does
not ask for. Clients: Claude Code (`claude mcp add`), Cursor (`.cursor/mcp.json`), Codex,
Copilot, Hermes Agent, or any MCP client.

## OpenAI Agents SDK, Codex-style guardrails

Status: **interface adapter; shape tested, not run against the SDK.**

```python
from sanchopanza.harness.openai_agents import tool_guardrail
check = tool_guardrail(guardian)
result = await check("shell", {"command": "..."})
# {"tripwire_triggered": bool, "output_info": {"action", "reason", "arguments"}}
```

Wrap it in the SDK's `@input_guardrail` and return `GuardrailFunctionOutput(result["output_info"],
result["tripwire_triggered"])`. Argument rewriting has no guardrail equivalent; call
`Guardian.before_tool` from a tool wrapper if the harness lets you replace arguments.

## LangChain, LangGraph and deepagents (middleware)

```python
from sanchopanza.harness.langchain import ToolSelectMiddleware

agent = create_agent(model, tools, middleware=[ToolSelectMiddleware(squire, always={"web_search"})])
```

`ToolSelectMiddleware` narrows `request.tools` on every model call. Tools are grouped by
`group_of` (default: the tool's `metadata["server"]`, else the prefix before the first `_`),
the squire asks one question per group ("would work on the last human message need this
group?") and the call goes on with the groups that pass, plus `always`. A group is dropped
only when its probability is low (`Thresholds.tools`, 0.35): the costly error here is
hiding a tool the agent needed, not paying for one it did not use. The selection is never
empty; with no human message, a single group, unnamed tools or a silent decider the request
passes untouched.

Tested in shape against a request-like object with `tools`, `messages` and `override(...)`,
which is what LangChain 1.x `ModelRequest` exposes; not yet against a live agent loop, and
not yet measured on a public bench. Requires `pip install sanchopanza[langchain]` for the real
`AgentMiddleware` base; without LangChain the class still imports and runs for tests.

## Cursor, Copilot, Hermes Agent and others

Three routes, in order of effort:

1. **MCP server** (above): works wherever MCP works, no code in the harness.
2. **Command hook**: if the harness runs hooks as processes with JSON in and out, point it at
   `sanchopanza hook` and map field names. Claude Code's protocol is the default; a different one
   is a ten-line wrapper around `sanchopanza.harness.claude_code.handle`.
3. **Middleware**: call `Guardian.before_tool` / `after_tool` from the harness's own tool
   middleware (a custom loop; for LangChain see the section above). The `Verdict` is three fields.

Contributions of tested adapters are welcome; put them in `sancho/harness/<name>.py` with a
docstring that says what is tested and what is not.
