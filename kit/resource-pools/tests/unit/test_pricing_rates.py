"""Structural validation of the rate lists in a pool's `pricing` hint."""

from __future__ import annotations

import pytest
from market_resource_pools import validate_pricing_rates


def _entry(**overrides):
    return {"asset": "usd", "rate": "0.5", "per": "hour", **overrides}


def test_absent_and_rateless_pricing_is_valid():
    assert validate_pricing_rates({}) == []
    assert validate_pricing_rates({"pricing": {"gpu": {"H100": {"settlements": []}}}}) == []


def test_family_and_keyed_rate_lists_are_valid_without_knowing_family_names():
    tags = {"pricing": {
        "gpu": {"H100": {"rates": [_entry(rate="80")]}},
        "fpga": {"rates": [_entry(), _entry(asset="0xabc")]},
        "memory": {"rates": []},
    }}
    assert validate_pricing_rates(tags) == []


@pytest.mark.parametrize(
    ("entry", "fragment"),
    [
        (_entry(rate=0.5), ".rate must be positive decimal text"),
        (_entry(rate="0"), ".rate must be positive decimal text"),
        (_entry(rate="1e3"), ".rate must be positive decimal text"),
        (_entry(asset=" usd"), ".asset must be a trimmed"),
        (_entry(per="Hour"), ".per must be a canonical"),
        ({"asset": "usd", "rate": "1"}, "exactly asset, rate, and per"),
    ],
)
def test_malformed_entries_are_named(entry, fragment):
    (problem,) = validate_pricing_rates({"pricing": {"cpu": {"rates": [entry]}}})
    assert problem.startswith("pricing.cpu.rates[0]")
    assert fragment in problem


def test_a_repeated_asset_and_a_non_list_are_refused():
    assert validate_pricing_rates(
        {"pricing": {"gpu": {"H100": {"rates": [_entry(), _entry()]}}}}
    ) == ["pricing.gpu.H100.rates[1].asset 'usd' appears more than once"]
    assert validate_pricing_rates({"pricing": {"cpu": {"rates": "0.5"}}}) == [
        "pricing.cpu.rates must be a list of rate entries"
    ]
