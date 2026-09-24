"""The cost meter. No network: a fake usage object is all it needs.

These pin the three things that, if they broke quietly, would put a wrong number in a paper:
the cache multipliers, the refusal to price an unknown model, and the zero-cache warning.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from meter import PRICES, Meter, UnknownModel, Usage, price_of  # noqa: E402


@dataclass
class FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class FakeResponse:
    usage: FakeUsage
    model: str = "claude-sonnet-5"


def test_an_unknown_model_raises_instead_of_guessing():
    with pytest.raises(UnknownModel):
        price_of("claude-imaginary-9")
    with pytest.raises(UnknownModel):
        Meter("claude-imaginary-9")


def test_prices_match_the_vendor_table():
    assert PRICES["claude-opus-5"] == (5.00, 25.00)
    assert PRICES["claude-sonnet-5"] == (2.00, 10.00)
    assert PRICES["claude-haiku-4-5"] == (1.00, 5.00)


def test_plain_input_and_output_cost_list_price():
    u = Usage(calls=1, input=1_000_000, output=1_000_000)
    assert u.cost("claude-sonnet-5") == pytest.approx(12.00)


def test_a_cached_read_costs_a_tenth_and_a_write_costs_more_than_full_price():
    """The whole point of the cache, and the reason narrowing a catalog can cost money."""
    read = Usage(calls=1, cache_read=1_000_000).cost("claude-sonnet-5")
    write = Usage(calls=1, cache_write=1_000_000).cost("claude-sonnet-5")
    plain = Usage(calls=1, input=1_000_000).cost("claude-sonnet-5")
    assert read == pytest.approx(plain * 0.10)
    assert write == pytest.approx(plain * 1.25)
    assert write > plain


def test_the_one_hour_ttl_is_not_the_default_and_costs_more():
    u = Usage(calls=1, cache_write=1_000_000)
    assert u.cost("claude-sonnet-5", cache_ttl="5m") == pytest.approx(2.50)
    assert u.cost("claude-sonnet-5", cache_ttl="1h") == pytest.approx(4.00)


def test_uncached_cost_prices_every_input_token_at_full_rate():
    """What the run would have cost with no cache: the cache's worth is the difference."""
    u = Usage(calls=1, input=100, cache_read=1000, cache_write=100, output=0)
    assert u.uncached_cost("claude-sonnet-5") == pytest.approx(1200 * 2.00 / 1e6)
    assert u.cost("claude-sonnet-5") < u.uncached_cost("claude-sonnet-5")


def test_the_meter_accumulates_by_label_and_writes_a_ledger(tmp_path):
    ledger = tmp_path / "usage.jsonl"
    meter = Meter("claude-opus-5", ledger=ledger)
    meter.add(FakeResponse(FakeUsage(input_tokens=100, output_tokens=10)), label="a", seconds=1.0)
    meter.add(FakeResponse(FakeUsage(input_tokens=200, output_tokens=20)), label="b", seconds=2.0)
    meter.add(FakeResponse(FakeUsage(input_tokens=300, output_tokens=30)), label="a")

    assert meter.total.calls == 3
    assert meter.total.input == 600
    assert meter.by_label["a"].calls == 2 and meter.by_label["a"].input == 400
    assert meter.total.seconds == pytest.approx(3.0)

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert [r["label"] for r in rows] == ["a", "b", "a"]
    assert rows[0]["input"] == 100


def test_a_response_without_usage_is_refused():
    meter = Meter("claude-opus-5")
    with pytest.raises(ValueError):
        meter.add(object())


def test_the_summary_shouts_when_nothing_was_read_from_cache():
    """A zero here is the expensive silent failure, so it cannot be left to a reader."""
    meter = Meter("claude-sonnet-5")
    for _ in range(3):
        meter.add(FakeResponse(FakeUsage(input_tokens=1000, output_tokens=10)))
    assert "ZERO" in meter.summary()

    warm = Meter("claude-sonnet-5")
    for _ in range(3):
        warm.add(FakeResponse(FakeUsage(input_tokens=10, cache_read_input_tokens=1000)))
    assert "ZERO" not in warm.summary()
    assert "the cache is worth" in warm.summary()


def test_as_dict_round_trips_as_json(tmp_path):
    meter = Meter("claude-opus-5", cache_ttl="1h")
    meter.add(FakeResponse(FakeUsage(input_tokens=5, output_tokens=1)), label="x")
    path = tmp_path / "usage.json"
    meter.write(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "claude-opus-5"
    assert data["cache_ttl"] == "1h"
    assert data["usage"]["calls"] == 1
    assert data["by_label"]["x"]["input"] == 5
