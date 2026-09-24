"""What the organization was actually billed, against what our meters claim.

    python benchmarks/billed.py --since 2026-09-24 \
        --ledger docs/results/2026-09-24-fifty/annotator-usage.jsonl

Needs `ANTHROPIC_ADMIN_API_KEY` (an `sk-ant-admin...` key). A normal `sk-ant-api...` key is
refused by these endpoints with a 401 and the message "The Admin API requires an Admin API
key or an organization-scoped API key", so this is the one number in the repository that a
project key cannot produce.

Why it exists. `benchmarks/meter.py` prices the tokens the API reported, which is exact
arithmetic and still not a bill. Between the two sits everything nobody metered: a script
written in a hurry, a run that crashed after spending, a smoke test. On 2026-09-24 that gap
was an entire 212-call annotation run whose cost was estimated out loud, never checked, and
wrong. **This tool closes the loop the other way round: it starts from the bill and asks
which of it our ledgers can account for.**

Three numbers come back and they mean different things:

  - **Billed** (`/v1/organizations/cost_report`): the authoritative amount, and the only one
    that is a bill. It is only available for *closed* days, so it says nothing about a run
    made in the last few hours.
  - **Priced usage** (`/v1/organizations/usage_report/messages` at list prices): available
    hourly, so it covers today. It is the same arithmetic `meter.py` does, applied to the
    organization's own token counts rather than to ours.
  - **Metered** (the `--ledger` files): what our own tooling recorded.

The difference between priced usage and metered is unmetered spend. If it is not near zero,
something ran without a meter and the next estimate will be a guess again.

The usage report covers the whole organization. `--api-key` narrows it to one key when the
organization has more than one; without it, other people's work on the same org counts as
unmetered, which is correct but not informative.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from meter import PRICES, Usage  # noqa: E402

BASE = "https://api.anthropic.com/v1/organizations"


class AdminKeyMissing(RuntimeError):
    pass


def _get(path: str, params: dict[str, object], key: str) -> dict:
    query = urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(
        f"{BASE}/{path}?{query}",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:400]
        if error.code == 401:
            raise AdminKeyMissing(
                "the Usage and Cost API refused this key. It needs an Admin API key "
                f"(sk-ant-admin...), not a project key. Server said: {body}"
            ) from error
        raise RuntimeError(f"HTTP {error.code} on {path}: {body}") from error


def usage_by_model(
    since: datetime.date, key: str, api_key_id: str | None
) -> tuple[dict[str, Usage], str | None]:
    """Hourly usage per model, plus the newest hour that actually reported anything.

    That second value is not a detail. The current hour is still open and reports
    nothing, so a reconciliation run minutes after a job sees the job in its own ledger
    and not in the organization's usage, and would call the difference negative
    unmetered spend. Measured on 2026-09-24: at 11:34 UTC the newest populated bucket
    was 10:00."""
    params: dict[str, object] = {
        "starting_at": f"{since.isoformat()}T00:00:00Z",
        "bucket_width": "1h",
        "limit": 168,
        "group_by[]": ["model", "api_key_id"],
    }
    body = _get("usage_report/messages", params, key)
    totals: dict[str, Usage] = collections.defaultdict(Usage)
    for bucket in body.get("data", []):
        for row in bucket.get("results", []):
            if api_key_id and row.get("api_key_id") != api_key_id:
                continue
            model = row.get("model") or "unknown"
            creation = row.get("cache_creation") or {}
            u = totals[model]
            u.calls += 1
            u.input += row.get("uncached_input_tokens") or 0
            u.output += row.get("output_tokens") or 0
            u.cache_read += row.get("cache_read_input_tokens") or 0
            u.cache_write += (creation.get("ephemeral_1h_input_tokens") or 0) + (
                creation.get("ephemeral_5m_input_tokens") or 0
            )
    poblados = [
        b["starting_at"]
        for b in body.get("data", [])
        if any(not api_key_id or r.get("api_key_id") == api_key_id for r in b.get("results", []))
    ]
    return dict(totals), (max(poblados) if poblados else None)


def billed(since: datetime.date, until: datetime.date, key: str) -> list[tuple[str, float]]:
    """The authoritative amount, per closed day. Today is never in here."""
    body = _get(
        "cost_report",
        {"starting_at": since.isoformat(), "ending_at": until.isoformat(), "limit": 31},
        key,
    )
    out = []
    for bucket in body.get("data", []):
        total = sum(float(r.get("amount") or 0.0) for r in bucket.get("results", []))
        out.append((bucket["starting_at"][:10], total))
    return out


def metered(ledgers: list[str]) -> tuple[float, int]:
    """Sum our own per-call ledgers. Unknown models are reported, not silently priced."""
    total, calls, unknown = 0.0, 0, set()
    for name in ledgers:
        path = pathlib.Path(name)
        if not path.exists():
            print(f"  (no ledger at {path})", file=sys.stderr)
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            model = row.get("model", "")
            if model not in PRICES:
                unknown.add(model)
                continue
            u = Usage(
                calls=1,
                input=row.get("input", 0),
                output=row.get("output", 0),
                cache_read=row.get("cache_read", 0),
                cache_write=row.get("cache_write", 0),
            )
            total += u.cost(model)
            calls += 1
    if unknown:
        print(f"  (ledger rows with unpriced models, skipped: {sorted(unknown)})", file=sys.stderr)
    return total, calls


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--since", required=True, help="YYYY-MM-DD, inclusive, UTC")
    p.add_argument("--until", default=None, help="YYYY-MM-DD exclusive; default tomorrow")
    p.add_argument("--ledger", action="append", default=[], help="a meter ledger .jsonl")
    p.add_argument("--api-key", default=None, help="narrow the usage report to one api_key_id")
    args = p.parse_args()

    key = os.environ.get("ANTHROPIC_ADMIN_API_KEY", "")
    if not key:
        print(
            "ANTHROPIC_ADMIN_API_KEY is not set. This is the only figure in the repository "
            "that a project key cannot produce.",
            file=sys.stderr,
        )
        return 2

    since = datetime.date.fromisoformat(args.since)
    until = (
        datetime.date.fromisoformat(args.until)
        if args.until
        else datetime.datetime.now(datetime.UTC).date() + datetime.timedelta(days=1)
    )

    print(f"# Billed against metered, {since} to {until} (UTC)\n")

    # The cost report only knows about days that are over. Asking it for a range whose
    # last day is today returns a 400, so the window is clamped to the closed part and
    # skipped entirely when there is none.
    today = datetime.datetime.now(datetime.UTC).date()
    close_end = min(until, today)
    rows = billed(since, close_end, key) if close_end > since else []
    closed = sum(amount for _, amount in rows)
    if rows:
        print("## Billed, per closed day (authoritative)\n")
        for day, amount in rows:
            print(f"- {day}: {amount:.4f} USD")
        print(f"\nTotal over closed days: **{closed:.4f} USD**")
        print(
            "\nThis is the whole organization. Today is not in it: the cost report only "
            "closes a day once it is over.\n"
        )
    else:
        print("No closed day in range, so there is no authoritative figure yet.\n")

    per_model, newest = usage_by_model(since, key, args.api_key)
    priced = sum(u.cost(m) for m, u in per_model.items() if m in PRICES)
    unpriced = [m for m in per_model if m not in PRICES]
    print("## Usage report, priced at list prices (covers today)\n")
    print("| Model | Uncached in | Cache read | Cache write | Out | At list prices |")
    print("|---|---|---|---|---|---|")
    for model, u in sorted(per_model.items()):
        cost = f"{u.cost(model):.4f} USD" if model in PRICES else "no list price"
        print(
            f"| {model} | {u.input:,} | {u.cache_read:,} | {u.cache_write:,} | "
            f"{u.output:,} | {cost} |"
        )
    print(f"\nPriced total: **{priced:.4f} USD**")
    if newest:
        print(
            f"\nNewest hour with data: **{newest}**. The current hour is still open and "
            "reports nothing, so anything run since then is missing from the table above. "
            "Re-run this an hour later before believing the gap below."
        )
    if unpriced:
        print(f"\nModels with no list price in `meter.py`, excluded: {sorted(unpriced)}")

    if args.ledger:
        ours, calls = metered(args.ledger)
        gap = priced - ours
        print("\n## What our own meters account for\n")
        print(f"- Ledgers: {len(args.ledger)}, {calls} metered calls, **{ours:.4f} USD**")
        print(f"- Priced usage over the same window: {priced:.4f} USD")
        share = ours / priced if priced else 0.0
        print(f"- **Unmetered: {gap:.4f} USD** ({1 - share:.0%} of the window)")
        print(
            "\nEverything not in a ledger is a run whose cost nobody will be able to state "
            "later. That is the failure this file exists to make visible."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
