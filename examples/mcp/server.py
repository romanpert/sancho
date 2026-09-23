"""Sancho's deliberate decision points as an MCP server over stdio.

    pip install sanchopanza[jev,mcp]
    TYPESAFE_API_KEY=... python examples/mcp/server.py

Claude Code:   claude mcp add sancho -- python examples/mcp/server.py
Cursor:        .cursor/mcp.json -> {"mcpServers": {"sancho": {"command": "python", "args": ["examples/mcp/server.py"]}}}
Codex:         same shape in its MCP config.

Tools: verify_citation, evaluate_plan, align_entities, classify_field, triage_text.
"""

from __future__ import annotations

import os

from sanchopanza import JsonlJournal, Squire
from sanchopanza.harness.mcp import build_server
from sanchopanza.providers import create

provider = "jev" if os.environ.get("TYPESAFE_API_KEY") else "null"
squire = Squire(create(provider), journal=JsonlJournal(os.environ.get("SANCHO_JOURNAL", "journal.jsonl")))

if __name__ == "__main__":
    build_server(squire).run()
