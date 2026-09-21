"""A research agent on the Claude Agent SDK with Sancho attached through hooks.

    TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=... python examples/claude_agent_sdk/minimal.py

Nothing in the agent loop changes. The squire rewrites the subagent tier when confident,
denies repeated searches, guards shell commands and reviews what subagents return.
"""

from __future__ import annotations

import asyncio
import os

from sancho import JsonlJournal, Squire, Thresholds
from sancho.harness import Guardian, HarnessConfig
from sancho.providers import create


async def main() -> None:
    from claude_agent_sdk import ClaudeAgentOptions, query

    from sancho.harness.claude_agent_sdk import hook_matchers

    provider = "jev" if os.environ.get("TYPESAFE_API_KEY") else "null"
    squire = Squire(
        create(provider),
        thresholds=Thresholds(allow_upgrade=False, max_usd=0.10),
        journal=JsonlJournal("journal.jsonl"),
        brief="Solar energy market in Colombia, 2026",
    )
    guardian = Guardian(
        squire,
        HarnessConfig(
            tiers={"light": "researcher-light", "default": "researcher", "deep": "researcher-deep"},
        ),
    )
    options = ClaudeAgentOptions(
        model="claude-sonnet-5",
        allowed_tools=["Agent", "WebSearch", "WebFetch", "Bash", "Read", "Write"],
        hooks=hook_matchers(guardian),
        max_budget_usd=2.0,
    )
    async for message in query(
        prompt="Size the distributed solar market in Colombia in 2026. Cite every figure.",
        options=options,
    ):
        print(message)
    print("squire:", squire.meter)


if __name__ == "__main__":
    asyncio.run(main())
