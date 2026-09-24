"""One place that knows what a call to the big model cost, and writes it down.

    from meter import Meter, PRICES

    meter = Meter("claude-opus-5", ledger=Path("run/usage.jsonl"))
    response = client.messages.create(...)
    meter.add(response, label="annotate:mw-17")
    print(meter.summary())

Why this file exists. The prices and the cache arithmetic were copied in
`benchmarks/ab/run.py` and `benchmarks/cache/run.py`, and a third tool - the second annotator
of 2026-09-24 - was written without any, so a run that cost real money produced no measured
figure at all. The estimate was stated out loud beforehand and never checked afterwards,
which is the failure this module exists to make impossible: **there is now one thing to reach
for, and reaching for it is less work than not.**

What it measures, and what it does not. `Meter.cost()` is a *client-side estimate*: list
prices times reported tokens. It is exact arithmetic over the numbers the API returns, and it
is still not a bill. Discounts, tier pricing and anything the account negotiated live on the
invoice, not here. The authoritative figure is the organization's Usage and Cost report,
which needs an **Admin API key** (`sk-ant-admin...`); a normal `sk-ant-api...` key is refused
with a 401 and the message "The Admin API requires an Admin API key or an organization-scoped
API key". Treat this module as the thing that catches an unmeasured run, and the Usage and
Cost report as the thing that settles what was paid.

Cache arithmetic. A cached read costs 0.1x base input, a five-minute write 1.25x and a
one-hour write 2x. `cache_creation_input_tokens` does not say which TTL was used, so the
multiplier is a parameter: pass `cache_ttl="1h"` on a meter for a job that sets
`ENABLE_PROMPT_CACHING_1H`, or the figure understates the write side by 60 %.

`cache_read_input_tokens` sitting at zero across repeated calls with a shared prefix is the
expensive silent failure, so `summary()` reports it whether or not anyone asked.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

# Anthropic list prices, USD per million tokens (input, output).
# Checked against the vendor's model table on 2026-09-24.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-5-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
CACHE_READ = 0.10
CACHE_WRITE = {"5m": 1.25, "1h": 2.00}


class UnknownModel(KeyError):
    """Raised rather than guessing a price. A silent default is how a bill goes unnoticed."""


def price_of(model: str) -> tuple[float, float]:
    try:
        return PRICES[model]
    except KeyError as error:
        raise UnknownModel(
            f"no list price for {model!r}; add it to benchmarks/meter.py PRICES rather than "
            "letting a run report a cost computed from the wrong number"
        ) from error


@dataclass(slots=True)
class Usage:
    """Token counts, summed. Every field is reported by the API; none is inferred."""

    calls: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    seconds: float = 0.0

    def add(self, usage: Any, seconds: float = 0.0) -> None:
        self.calls += 1
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.seconds += seconds

    def cost(self, model: str, *, cache_ttl: str = "5m") -> float:
        """List-price estimate. Cached reads at 0.1x, writes at the TTL's multiplier."""
        rate_in, rate_out = price_of(model)
        write = CACHE_WRITE[cache_ttl]
        return (
            self.input * rate_in
            + self.cache_read * rate_in * CACHE_READ
            + self.cache_write * rate_in * write
            + self.output * rate_out
        ) / 1_000_000

    def uncached_cost(self, model: str) -> float:
        """What the same tokens would have cost with no cache at all.

        The difference against `cost` is what the prompt cache is worth on this run. It is
        also the number that makes a zero in `cache_read` visible as money rather than as a
        field nobody read.
        """
        rate_in, rate_out = price_of(model)
        total_in = self.input + self.cache_read + self.cache_write
        return (total_in * rate_in + self.output * rate_out) / 1_000_000


class Meter:
    """Accumulates usage across calls, optionally appending one line per call to a ledger.

    Thread and coroutine safe for the accumulate-and-append pattern used by the benchmarks:
    a lock guards both the counters and the append, so concurrent workers cannot interleave.
    """

    def __init__(
        self,
        model: str,
        *,
        ledger: pathlib.Path | str | None = None,
        cache_ttl: str = "5m",
    ) -> None:
        price_of(model)  # fail now, not after spending
        if cache_ttl not in CACHE_WRITE:
            raise ValueError(f"cache_ttl must be one of {sorted(CACHE_WRITE)}")
        self.model = model
        self.cache_ttl = cache_ttl
        self.total = Usage()
        self.by_label: dict[str, Usage] = {}
        self._ledger = pathlib.Path(ledger) if ledger else None
        self._lock = threading.Lock()
        if self._ledger is not None:
            self._ledger.parent.mkdir(parents=True, exist_ok=True)

    def add(self, response: Any, *, label: str = "", seconds: float = 0.0) -> None:
        """Record one response. `label` groups calls, e.g. an arm name or a case id."""
        usage = getattr(response, "usage", None)
        if usage is None:
            raise ValueError("response carries no usage; nothing to meter")
        with self._lock:
            self.total.add(usage, seconds)
            group = self.by_label.setdefault(label, Usage())
            group.add(usage, seconds)
            if self._ledger is not None:
                row = {
                    "ts": time.time(),
                    "label": label,
                    "model": getattr(response, "model", self.model),
                    "input": getattr(usage, "input_tokens", 0) or 0,
                    "output": getattr(usage, "output_tokens", 0) or 0,
                    "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                    "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    "seconds": round(seconds, 3),
                }
                with self._ledger.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    @property
    def cost(self) -> float:
        return self.total.cost(self.model, cache_ttl=self.cache_ttl)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "cache_ttl": self.cache_ttl,
            "cost_usd": round(self.cost, 6),
            "uncached_cost_usd": round(self.total.uncached_cost(self.model), 6),
            "usage": asdict(self.total),
            "by_label": {k: asdict(v) for k, v in sorted(self.by_label.items())},
        }

    def summary(self) -> str:
        """One block, always including the cache line, because a zero there is the bug."""
        u = self.total
        cost = self.cost
        uncached = u.uncached_cost(self.model)
        lines = [
            f"{u.calls} calls to {self.model}: {u.input:,} input, {u.output:,} output, "
            f"{u.cache_read:,} cached read, {u.cache_write:,} cached write",
            f"cost (list prices, client-side estimate): {cost:.4f} USD"
            + (f", {cost / u.calls * 1e6:.1f} millionths per call" if u.calls else ""),
        ]
        if u.cache_read or u.cache_write:
            saved = uncached - cost
            lines.append(
                f"without the cache the same tokens would be {uncached:.4f} USD: "
                f"the cache is worth {saved:.4f} USD here ({saved / uncached:.0%})"
            )
        elif u.calls > 1:
            lines.append(
                "cache_read_input_tokens is ZERO across every call. If these calls shared a "
                "prefix, something is invalidating it and the run is paying full price in "
                "silence."
            )
        return "\n".join(lines)

    def write(self, path: pathlib.Path | str) -> None:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=1), encoding="utf-8")


@dataclass(slots=True)
class Timed:
    """Context manager returning elapsed seconds, so `add(..., seconds=t.seconds)` is easy."""

    seconds: float = field(default=0.0)
    _start: float = field(default=0.0)

    def __enter__(self) -> Timed:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.seconds = time.perf_counter() - self._start
