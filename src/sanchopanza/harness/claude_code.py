"""Command-line hook for Claude Code (`sanchopanza hook`), and any harness with the same protocol.

Claude Code runs hooks as processes: JSON on stdin, JSON on stdout. In `settings.json`:

    {"hooks": {
      "PreToolUse": [{"matcher": "Agent|WebSearch|Bash",
                      "hooks": [{"type": "command", "command": "sanchopanza hook"}]}],
      "PostToolUse": [{"matcher": "Agent",
                       "hooks": [{"type": "command", "command": "sanchopanza hook"}]}]}}

Configuration is by environment, because a hook process has nothing else:

    SANCHO_PROVIDER   jev | recorded | null (default: jev if TYPESAFE_API_KEY is set, else null)
    TYPESAFE_API_KEY  for the Jev provider
    SANCHO_FIXTURE    path of a recording for the recorded provider
    SANCHO_JOURNAL    path of the JSONL journal (default: ~/.sancho/journal.jsonl)
    SANCHO_TIERS      "light=haiku-agent,default=general-purpose,deep=opus-agent" (optional)
    SANCHO_CHEAP_SEARCH  "1" when a cheap search tool is available to the agent

Each hook process is a fresh squire, so the per-job budget and the repeated-query memory
do not persist across calls. That is the price of the process model; the SDK adapter keeps
them.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from ..contract import Decider
from ..journal import JsonlJournal
from ..points.routing import Tier
from ..policy import Thresholds
from ..squire import Squire
from .claude_agent_sdk import post_tool_use, pre_tool_use
from .generic import Guardian, HarnessConfig


def decider_from_env(env: dict[str, str] | None = None) -> Decider:
    env = env if env is not None else dict(os.environ)
    from ..providers import create

    provider = env.get("SANCHO_PROVIDER")
    if not provider:
        provider = "jev" if env.get("TYPESAFE_API_KEY") else "null"
    if provider == "recorded":
        return create("recorded", path=env.get("SANCHO_FIXTURE", "fixtures/public-benches.jsonl"))
    if provider == "jev":
        return create("jev", api_key=env.get("TYPESAFE_API_KEY"))
    return create("null")


def config_from_env(env: dict[str, str] | None = None) -> HarnessConfig:
    env = env if env is not None else dict(os.environ)
    tiers: dict[Tier, str] = {}
    for part in filter(None, env.get("SANCHO_TIERS", "").split(",")):
        tier, _, name = part.partition("=")
        if tier.strip() in ("light", "default", "deep") and name.strip():
            tiers[tier.strip()] = name.strip()  # type: ignore[index]
    cheap = env.get("SANCHO_CHEAP_SEARCH", "") in ("1", "true", "yes")
    return HarnessConfig(tiers=tiers, cheap_search_available=lambda: cheap)


def guardian_from_env(env: dict[str, str] | None = None) -> Guardian:
    env = env if env is not None else dict(os.environ)
    journal_path = Path(env.get("SANCHO_JOURNAL") or Path.home() / ".sancho" / "journal.jsonl")
    thresholds = Thresholds.from_mapping(
        {k[len("SANCHO_T_") :].lower(): v for k, v in env.items() if k.startswith("SANCHO_T_")}
    )
    squire = Squire(
        decider_from_env(env), thresholds=thresholds, journal=JsonlJournal(journal_path)
    )
    return Guardian(squire, config_from_env(env))


async def handle(input_data: dict[str, Any], guardian: Guardian) -> dict[str, Any]:
    event = str(input_data.get("hook_event_name", "PreToolUse"))
    if event == "PostToolUse":
        return await post_tool_use(guardian)(input_data)
    return await pre_tool_use(guardian)(input_data)


def main(argv: list[str] | None = None) -> int:
    raw = sys.stdin.read()
    try:
        input_data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0  # malformed input: let the tool run; never block on our own bug
    try:
        output = asyncio.run(handle(input_data, guardian_from_env()))
    except Exception:  # fail-open at the process boundary as well
        return 0
    if output:
        sys.stdout.write(json.dumps(output, ensure_ascii=False))
    return 0
