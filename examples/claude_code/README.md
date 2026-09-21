# Sancho as a Claude Code hook

Claude Code runs hooks as processes: JSON on stdin, JSON on stdout. `sancho hook` reads a
`PreToolUse` or `PostToolUse` event and answers with the same `hookSpecificOutput` shape the
Claude Agent SDK uses.

1. `pip install sancho[jev]` in an environment Claude Code can see (`which sancho`).
2. Put `settings.json` from this folder in `.claude/settings.json` (project) or merge it into
   `~/.claude/settings.json` (user).
3. Export `TYPESAFE_API_KEY`. Without it the hook runs the `null` provider and changes nothing.

Environment variables the hook reads:

| Variable | Meaning |
|---|---|
| `SANCHO_PROVIDER` | `jev`, `recorded`, `null`. Default: `jev` if a key is set, else `null` |
| `SANCHO_FIXTURE` | recording to replay with `recorded` |
| `SANCHO_JOURNAL` | JSONL journal path. Default `~/.sancho/journal.jsonl` |
| `SANCHO_TIERS` | `light=<subagent>,default=<subagent>,deep=<subagent>`; the names of your subagents |
| `SANCHO_CHEAP_SEARCH` | `1` if the agent has a cheap search tool the hook may point to |
| `SANCHO_T_<name>` | override a threshold, e.g. `SANCHO_T_ACT=0.8` |

What changes in a session:

- `Agent` / `Task` calls get their `subagent_type` rewritten to the tier the squire chose
  (only when it is confident; otherwise nothing happens).
- `WebSearch` is denied with a reason when the query repeats one from this hook process, or
  when a cheap engine would do and `SANCHO_CHEAP_SEARCH=1`.
- `Bash` is denied with a reason when the deny-list or the squire flags the command.
- After an `Agent` returns, a one-line review is appended as additional context when there
  is a signal (facts without sources, exhausted line, did not answer).

Every decision is a line in the journal. Read it before you change a threshold.

Limitation of the process model: each hook call is a fresh squire, so the per-job budget
and the repeated-query memory are per call. The SDK adapter keeps both across a job.
