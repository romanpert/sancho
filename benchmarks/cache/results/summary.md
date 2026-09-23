# Narrowing a tool catalog: when it saves and when it costs

**2026-09-24, claude-sonnet-5, 8 turns per arm, 4 arms, 0.70 USD of real spend.**
Reproduce with `python benchmarks/cache/run.py --turns 8`, or see the arithmetic for free
with `--dry`. Raw per-arm counters in `runs.json`.

The package has a tool-selection point, and the arithmetic for it looks irresistible:
Anthropic reports a five-server MCP setup at 58 tools and about 55k tokens of definitions
before any work begins, and a peak of 134k
([Anthropic, advanced tool use, 2025-11-24](https://www.anthropic.com/engineering/advanced-tool-use)).
Drop two thirds of that and you have dropped two thirds of a large bill.

You have not. Tool definitions are the very front of the prompt prefix, and the caching
hierarchy is `tools -> system -> messages`: changing the tool array invalidates all three.
A cached read costs 0.1x a base input token; a write costs 1.25x. So the question is not how
many schema tokens a selector removes, it is **how often the selector changes its mind**.

Four arms, identical in model, system prompt, questions and turn count. Each arm tags its
tool descriptions with its own name so it cannot read a cache another arm wrote.

| Arm | Tools per turn | Cached reads | Cache writes | Uncached in | Out | Cost | vs `once` |
|---|---|---|---|---|---|---|---|
| `static` | 58, fixed | 201,957 | 28,851 | 5,511 | 1,519 | 0.13873 USD | 1.75x |
| `once` | 28, fixed | 98,567 | 14,081 | 4,741 | 1,476 | **0.07916 USD** | 1.00x |
| `reselect` | 28 / 58 alternating | 129,312 | 43,104 | 4,844 | 1,439 | 0.15770 USD | 1.99x |
| `churn` | a different 28-30 each turn | **0** | 117,148 | 7,071 | 2,163 | 0.32864 USD | **4.15x** |

## What it says

**Narrowing once is worth 43 %.** `once` against `static`, same conversation, same model:
0.079 against 0.139 USD. One decision, taken before the first request, when there is no
prefix to invalidate, and the saving then applies to every turn of the session.

**Narrowing on every turn costs more than never narrowing at all.** `reselect` alternates
between two subsets and lands at 0.158 against `static`'s 0.139. It reads fewer schema
tokens and pays for them with three extra cache writes: 43,104 against 28,851. The schema
saving is real and it is smaller than what the rebuild costs.

**An unstable selector is a catastrophe, and the counter that shows it is a zero.** `churn`
presents a different subset each turn and reads **nothing** from cache across eight turns:
117,148 tokens written, not one read. It costs 4.15x the arm that took the same decision
once, and 2.4x the arm that took no decision at all. The zero is the whole finding: because
tools sit ahead of everything, a changing tool set stops the *conversation* from caching
too, not just the schemas.

So the rule the package documents is now measured rather than cited: **narrow once, at the
start of a session, and never per turn.** Where a harness genuinely needs the tool set to
change mid-session, the cache-preserving channels are Anthropic's tool search (schemas are
appended, not swapped) and the `tool_addition` / `tool_removal` blocks on a `system` message
with `defer_loading`, not a rewritten `tools` array.

## What it does not say

It is one model, one synthetic catalog and eight turns. The catalog is 58 tools at about
18k tokens, a third of the size Anthropic reports for 58 real MCP tools, so the schema-side
saving here is **understated** relative to a real setup; the cache-side penalty does not
depend on catalog size in the same way. It measures cost, not answer quality: the arms were
asked questions that need no tool call, so nothing here says whether a narrowed catalog
answers as well. The tool-selection point's own accuracy is still unmeasured
(`docs/paper.md`, pending item 7).

## The first run of this benchmark was wrong

Worth recording, because the error is the kind that flatters a result. In the first run all
arms shared one catalog. `static` ran first and wrote the 58-tool prefix; `once` wrote the
28-tool prefix; `reselect` then alternated between two prefixes **that were already in the
cache**, read both for free, and came out the cheapest of the three at 0.062 USD. Read
without care that number says the naive wiring is the best one.

It is an artifact of the order the arms ran in. The prefix cache is keyed by the bytes of
the prefix, not by the conversation, so an arm inherits whatever an earlier arm wrote. The
fix is the per-arm tag in every tool description, and the `churn` arm, which exists because
that first run also taught us the real risk is not *narrowing* but *instability*: two stable
subsets cache as two entries and then read cheaply, while a subset that is new every turn
never reads at all.
