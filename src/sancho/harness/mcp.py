"""The decision points an agent asks for on purpose, exposed as MCP tools.

Hooks cover what happens without the model asking (model per subtask, search tier, shell
guard, thread review). These are the ones the orchestrator calls deliberately:

- `verify_citation`: quote present in code, meaning by the decider, doubt to review.
- `evaluate_plan`: priority, saturation, tier and dependency waves for a round's lines.
- `align_entities`: same real-world entity or not, with a grey zone.
- `classify_field`: free text to a closed vocabulary, with `other` and abstention.
- `triage_text`: is this text worth the large model's context for this purpose?

Requires `pip install sancho[mcp]`. Works with any MCP client: Claude Code, Cursor, Codex,
Copilot, Hermes or a custom harness.

    from sancho.harness.mcp import build_server
    build_server(squire).run()          # stdio
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ..points.citation import ADVICE
from ..squire import Squire

MAX_LINES = 25


def parse_lines(raw: Any) -> list[dict[str, str]]:
    """Accept JSON (list of {title, goal}) or plain text with one line per line."""
    if isinstance(raw, list):
        lines = raw
    else:
        text = str(raw or "").strip()
        try:
            lines = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            lines = [
                {"title": row.strip(" -*"), "goal": ""} for row in text.splitlines() if row.strip()
            ]
    if not isinstance(lines, list):
        return []
    return [
        {"title": str(row.get("title", "")), "goal": str(row.get("goal", ""))}
        for row in lines
        if isinstance(row, Mapping) and str(row.get("title", "")).strip()
    ][:MAX_LINES]


def parse_options(raw: Any) -> dict[str, str]:
    """Accept a JSON {name: description}, a JSON list of names, or names separated by |."""
    if isinstance(raw, Mapping):
        return {str(k): str(v) for k, v in raw.items()}
    text = str(raw or "").strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        value = [part.strip() for part in text.split("|") if part.strip()]
    if isinstance(value, Mapping):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        return {str(v): "" for v in value}
    return {}


def build_server(squire: Squire, *, name: str = "sancho") -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("install sancho[mcp] to expose the squire as MCP tools") from error

    server = FastMCP(name)

    @server.tool()
    async def verify_citation(claim: str, quote: str, source_text: str, url: str = "") -> str:
        """Check that a quote exists in the source text and that the source supports the claim.
        Returns supported | contradicted | unsupported | fabricated | review with confidence."""
        verdict, confidence = await squire.verify_citation(
            claim=claim, quote=quote, source=source_text
        )
        return f"Verdict: {verdict} (confidence {confidence:.2f}) for {url}. {ADVICE[verdict]}"

    @server.tool()
    async def evaluate_plan(lines: str, findings: str = "") -> str:
        """Prioritize a plan before launching it. `lines` is JSON [{"title", "goal"}].
        Returns each line with priority (0-1), parallel, saturated, tier, source kind,
        dependencies and wave. Call it once per round."""
        parsed = parse_lines(lines)
        if not parsed:
            return 'No lines received. Pass JSON [{"title", "goal"}].'
        return json.dumps(
            await squire.evaluate_plan(parsed, findings=findings), ensure_ascii=False, indent=1
        )

    @server.tool()
    async def align_entities(a: str, context_a: str, b: str, context_b: str) -> str:
        """Decide whether two mentions (person, organization, law, ruling, place) are the same
        entity, reading each one's context. Returns same | different | not_sure with probability."""
        same, p = await squire.same_entity(a=a, context_a=context_a, b=b, context_b=context_b)
        label = "not_sure" if same is None else ("same" if same else "different")
        advice = {
            "same": "Merge the records.",
            "different": "Do not merge.",
            "not_sure": "Note the doubt and do not merge.",
        }[label]
        return f"Verdict: {label} (probability of same entity {p:.2f}). {advice}"

    @server.tool()
    async def classify_field(field: str, text: str, options: str, context: str = "") -> str:
        """Assign free text to one category of a closed vocabulary. `options` is JSON
        {category: description} or a list. Returns the category with probability, or
        not_sure below threshold: then leave the field null and note why."""
        opts = parse_options(options)
        if len(opts) < 2:
            return "At least two options are needed: {category: description} as JSON."
        category, p, dist = await squire.classify(
            field=field, text=text, options=opts, context=context
        )
        top = ", ".join(f"{k} {v:.2f}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1])[:3])
        if category is None:
            return f"not_sure. Distribution: {top}. Leave the field null and note the doubt."
        return f"{category} (probability {p:.2f}). Distribution: {top}."

    @server.tool()
    async def triage_text(purpose: str, text: str, title: str = "", url: str = "") -> str:
        """Say whether a fetched text is worth reading for `purpose`: relevance, evidence,
        injection and source kind. In doubt it says keep."""
        result = await squire.triage_page(purpose=purpose, title=title, url=url, text=text)
        return json.dumps(
            {
                "keep": result.keep,
                "reason": result.reason,
                "relevance": round(result.relevance, 2),
                "evidence": round(result.evidence, 2),
                "injection": round(result.injection, 2),
                "source_kind": result.source_kind,
            }
        )

    return server
