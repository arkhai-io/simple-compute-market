"""The asking-rate declaration's three-tier resolution."""

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


class TestStatedNull:
    """A stated ``null`` is malformed, never absent: it holds the pool."""

    @pytest.mark.parametrize(
        "tags",
        [
            pytest.param({"asking_rates": None}, id="whole tag"),
            pytest.param({"asking_rates": {"vm": None}}, id="one mode"),
        ],
    )
    def test_a_stated_null_holds_at_read(self, tags):
        resolution = _resolve(tags)
        assert resolution.unreadable
        assert resolution.source == ASKING_RATE_SOURCE_HINT

    def test_a_null_for_another_mode_leaves_this_mode_unstated(self):
        resolution = _resolve({"asking_rates": {"bare_metal": None}})
        assert resolution.source == ASKING_RATE_SOURCE_NONE
