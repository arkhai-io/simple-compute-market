"""The asking-rate declaration's structure and its three-tier resolution."""

from __future__ import annotations

import hashlib
import json

import pytest

from market_resource_pools import (
    ASKING_RATE_SOURCE_HINT,
    ASKING_RATE_SOURCE_NONE,
    ASKING_RATE_SOURCE_OVERRIDE,
    AskingRate,
    resolve_asking_rates,
    validate_asking_rates,
)

H100_1 = {"gpu": {"model": "H100", "count": 1}}
H100_8 = {"gpu": {"model": "H100", "count": 8}, "memory": {"gib": 512}}


def _digest(shape) -> str:
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


def _vocabulary(shape) -> list[str]:
    """A stand-in domain vocabulary: every shape must name a GPU model."""
    return [] if shape.get("gpu", {}).get("model") else ["gpu.model is required"]


def _entry(shape=H100_1, amount="2.10", asset="usd", period="hour"):
    return {"shape": shape, "amount": amount, "asset": asset, "period": period}


def _resolve(policy_tags, override=None):
    return resolve_asking_rates(
        policy_tags,
        "vm",
        override_rates=override,
        shape_digest=_digest,
        shape_problems=_vocabulary,
    )


class TestStructure:
    def test_absent_is_valid(self):
        assert validate_asking_rates({}) == []

    def test_a_well_formed_declaration_is_valid(self):
        assert validate_asking_rates({"asking_rates": {"vm": [_entry(), _entry(H100_8)]}}) == []

    def test_an_empty_mode_list_is_valid(self):
        assert validate_asking_rates({"asking_rates": {"vm": []}}) == []

    @pytest.mark.parametrize(
        "amount",
        ["0", "0.00", "-1", "+1", "1e3", "01", "1.", ".5", 2.1, ""],
    )
    def test_an_amount_that_is_not_positive_plain_decimal_text_is_refused(self, amount):
        problems = validate_asking_rates({"asking_rates": {"vm": [_entry(amount=amount)]}})
        assert any("amount" in p for p in problems)

    @pytest.mark.parametrize("amount", ["0.01", "16", "16.000000000000000001"])
    def test_boundary_amounts_are_accepted(self, amount):
        assert validate_asking_rates({"asking_rates": {"vm": [_entry(amount=amount)]}}) == []

    def test_a_missing_part_is_refused(self):
        entry = _entry()
        del entry["asset"]
        problems = validate_asking_rates({"asking_rates": {"vm": [entry]}})
        assert problems == ["asking_rates.vm[0]: missing asset"]

    def test_an_unknown_key_is_refused(self):
        problems = validate_asking_rates({"asking_rates": {"vm": [{**_entry(), "rate": "1"}]}})
        assert problems == ["asking_rates.vm[0]: unknown rate"]

    def test_an_untrimmed_asset_is_refused(self):
        problems = validate_asking_rates({"asking_rates": {"vm": [_entry(asset=" usd")]}})
        assert any("asset" in p for p in problems)

    @pytest.mark.parametrize("period", ["Hour", " hour", "per hour", "", 1])
    def test_a_period_that_is_not_a_canonical_unit_token_is_refused(self, period):
        problems = validate_asking_rates({"asking_rates": {"vm": [_entry(period=period)]}})
        assert problems == ["asking_rates.vm[0]: period must be a canonical lowercase unit token"]

    def test_an_unknown_period_is_structurally_valid(self):
        """Which periods are accepted is the reading version's to say."""
        assert validate_asking_rates({"asking_rates": {"vm": [_entry(period="month")]}}) == []

    def test_a_non_mapping_declaration_is_refused(self):
        assert validate_asking_rates({"asking_rates": ["2.10"]}) == [
            "asking_rates must be a mapping of offering mode to a list of rates"
        ]


class TestResolution:
    def test_no_declaration_and_no_override_publishes_no_rate(self):
        resolution = _resolve({})
        assert resolution.source == ASKING_RATE_SOURCE_NONE
        assert resolution.rate_for(_digest(H100_1)) is None

    def test_a_pool_declaration_prices_each_shape_by_digest(self):
        resolution = _resolve(
            {"asking_rates": {"vm": [_entry(), _entry(H100_8, amount="16.00")]}}
        )
        assert resolution.source == ASKING_RATE_SOURCE_HINT
        assert resolution.rate_for(_digest(H100_1)) == AskingRate("2.10", "usd", "hour")
        assert resolution.rate_for(_digest(H100_8)).amount == "16.00"

    def test_another_modes_declaration_prices_nothing(self):
        resolution = _resolve({"asking_rates": {"bare_metal": [_entry()]}})
        assert resolution.source == ASKING_RATE_SOURCE_NONE

    def test_an_override_replaces_the_pool_declaration_as_a_whole(self):
        resolution = _resolve(
            {"asking_rates": {"vm": [_entry(), _entry(H100_8)]}},
            override=[_entry(amount="1.90")],
        )
        assert resolution.source == ASKING_RATE_SOURCE_OVERRIDE
        assert resolution.rate_for(_digest(H100_1)).amount == "1.90"
        assert resolution.rate_for(_digest(H100_8)) is None

    def test_an_empty_override_withholds_every_rate(self):
        resolution = _resolve({"asking_rates": {"vm": [_entry()]}}, override=[])
        assert resolution.source == ASKING_RATE_SOURCE_OVERRIDE
        assert not resolution.unreadable
        assert resolution.rate_for(_digest(H100_1)) is None

    def test_a_shape_outside_the_domain_vocabulary_holds_the_pool(self):
        resolution = _resolve({"asking_rates": {"vm": [_entry({"gpu": {"count": 1}})]}})
        assert resolution.unreadable
        assert resolution.rates == {}

    def test_a_period_this_version_does_not_accept_holds_the_pool(self):
        resolution = _resolve({"asking_rates": {"vm": [_entry(period="month")]}})
        assert resolution.unreadable
        assert "period" in resolution.problems[0]

    def test_two_entries_pricing_one_shape_hold_the_pool(self):
        resolution = _resolve({"asking_rates": {"vm": [_entry(), _entry(amount="3.00")]}})
        assert resolution.unreadable
        assert "already prices" in resolution.problems[0]

    def test_an_unreadable_override_does_not_fall_through(self):
        resolution = _resolve({"asking_rates": {"vm": [_entry()]}}, override="2.10")
        assert resolution.source == ASKING_RATE_SOURCE_OVERRIDE
        assert resolution.unreadable

    def test_a_non_mapping_pool_declaration_holds_the_pool(self):
        resolution = _resolve({"asking_rates": ["2.10"]})
        assert resolution.unreadable

    def test_a_priced_shape_no_listing_publishes_is_reported(self):
        resolution = _resolve({"asking_rates": {"vm": [_entry(), _entry(H100_8)]}})
        assert resolution.unpublished([_digest(H100_1)]) == {_digest(H100_8): H100_8}
