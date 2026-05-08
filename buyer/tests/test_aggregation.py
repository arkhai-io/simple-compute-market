"""Tests for the across-seller aggregation policy registry.

Covers:
  * The three built-in policies (cheapest_first, registry_order,
    random_shuffle, priceless_last) reorder/filter as expected.
  * register_aggregation_policy + load_aggregation_policy round-trip
    so an operator can plug in a custom callable.
  * load_aggregation_policy raises on an unknown name.
  * BuyConfig.aggregation_policy threads through run_buy: a policy
    that filters everything out yields no_matches.
"""
from __future__ import annotations

import json
import random
from typing import Any
from unittest.mock import MagicMock

import pytest

from market_buyer.aggregation import (
    DEFAULT_POLICY_NAME,
    list_aggregation_policies,
    load_aggregation_policy,
    register_aggregation_policy,
)
from market_buyer.buy_orchestrator import BuyConfig, BuyConstraints, run_buy


def _match(listing_id: str, *, price: int | None = None, seller: str = "http://s") -> dict[str, Any]:
    """Helper. Builds a registry match dict with the given advertised price."""
    demand: dict[str, Any] = {"token": "MOCK"}
    if price is not None:
        demand["amount"] = price
    return {
        "listing_id": listing_id,
        "seller": seller,
        "demand_resource": demand,
    }


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------


class TestCheapestFirst:
    def test_sorts_by_price_ascending(self):
        policy = load_aggregation_policy("cheapest_first")
        matches = [_match("a", price=300), _match("b", price=100), _match("c", price=200)]
        out = policy(matches)
        assert [m["listing_id"] for m in out] == ["b", "c", "a"]

    def test_priceless_listings_sort_to_end(self):
        policy = load_aggregation_policy("cheapest_first")
        matches = [
            _match("priceless1"),
            _match("priced", price=500),
            _match("priceless2", price=0),
        ]
        out = policy(matches)
        # Priced first, priceless last (in original order within bucket).
        assert out[0]["listing_id"] == "priced"
        assert {m["listing_id"] for m in out[1:]} == {"priceless1", "priceless2"}

    def test_serialised_demand_string_is_parsed(self):
        """The registry sometimes returns demand_resource as a JSON string."""
        policy = load_aggregation_policy("cheapest_first")
        matches = [
            {"listing_id": "a", "demand_resource": json.dumps({"amount": 200})},
            {"listing_id": "b", "demand_resource": json.dumps({"amount": 100})},
        ]
        out = policy(matches)
        assert [m["listing_id"] for m in out] == ["b", "a"]

    def test_default_is_cheapest_first(self):
        assert DEFAULT_POLICY_NAME == "cheapest_first"


class TestRegistryOrder:
    def test_passes_through(self):
        policy = load_aggregation_policy("registry_order")
        matches = [_match("a", price=300), _match("b", price=100)]
        out = policy(matches)
        assert [m["listing_id"] for m in out] == ["a", "b"]

    def test_returns_a_copy(self):
        policy = load_aggregation_policy("registry_order")
        matches = [_match("a")]
        out = policy(matches)
        out.append(_match("b"))
        assert len(matches) == 1


class TestRandomShuffle:
    def test_returns_same_set(self):
        policy = load_aggregation_policy("random_shuffle")
        matches = [_match(str(i), price=i * 10) for i in range(10)]
        out = policy(matches)
        assert {m["listing_id"] for m in out} == {m["listing_id"] for m in matches}
        assert len(out) == len(matches)

    def test_does_not_mutate_input(self):
        policy = load_aggregation_policy("random_shuffle")
        original = [_match(str(i)) for i in range(5)]
        snapshot = [m["listing_id"] for m in original]
        policy(original)
        assert [m["listing_id"] for m in original] == snapshot


class TestPricelessLast:
    def test_priced_first_then_priceless(self):
        policy = load_aggregation_policy("priceless_last")
        matches = [
            _match("priceless1"),
            _match("priced_high", price=500),
            _match("priceless2"),
            _match("priced_low", price=100),
        ]
        out = policy(matches)
        ids = [m["listing_id"] for m in out]
        assert ids == ["priced_low", "priced_high", "priceless1", "priceless2"]


# ---------------------------------------------------------------------------
# Pluggability
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_unknown_policy_raises(self):
        with pytest.raises(ValueError, match="Unknown across-seller aggregation policy"):
            load_aggregation_policy("does_not_exist")

    def test_none_returns_default(self):
        # Same callable as cheapest_first.
        assert load_aggregation_policy(None) is load_aggregation_policy("cheapest_first")

    def test_register_custom_policy(self):
        @register_aggregation_policy("test_reverse")
        def _reverse(matches):
            return list(reversed(matches))
        assert "test_reverse" in list_aggregation_policies()
        out = load_aggregation_policy("test_reverse")(
            [_match("a"), _match("b"), _match("c")]
        )
        assert [m["listing_id"] for m in out] == ["c", "b", "a"]

    def test_register_overwrites(self):
        """Re-registering the same name replaces the old binding (useful in tests)."""
        @register_aggregation_policy("test_double")
        def _v1(matches):
            return matches[:1]

        @register_aggregation_policy("test_double")
        def _v2(matches):
            return matches[-1:]

        out = load_aggregation_policy("test_double")(
            [_match("a"), _match("b"), _match("c")]
        )
        assert [m["listing_id"] for m in out] == ["c"]


# ---------------------------------------------------------------------------
# Integration with run_buy
# ---------------------------------------------------------------------------


class TestRunBuyIntegration:
    def test_aggregation_filters_all_yields_no_matches(self):
        """A custom policy that filters everything out yields no_matches."""
        @register_aggregation_policy("test_filter_all")
        def _drop_all(matches):
            return []

        config = BuyConfig(
            registry_urls=["http://registry"],
            buyer_address="0xbuyer",
            buyer_private_key="0xpk",
            ssh_public_key="ssh-rsa ...",
            aggregation_policy="test_filter_all",
        )
        constraints = BuyConstraints(duration_seconds=3600)

        # Pre-supply matches so query_registry_for_matches is bypassed.
        result = run_buy(
            config=config,
            constraints=constraints,
            create_escrow=lambda terms: pytest.fail("escrow shouldn't run"),
            matches=[_match("a", price=100), _match("b", price=200)],
        )
        assert result.status == "no_matches"

    def test_aggregation_reorders_match_iteration(self):
        """The orchestrator iterates matches in policy order, not registry order.

        We verify by setting up a custom policy that pins listing 'b'
        first and using a fake negotiator that records the iteration
        order.
        """
        seen: list[str] = []

        @register_aggregation_policy("test_b_first")
        def _b_first(matches):
            return sorted(matches, key=lambda m: 0 if m["listing_id"] == "b" else 1)

        # Patch negotiate_with_seller to record + immediately fail so we
        # iterate through all matches without doing real HTTP.
        from unittest.mock import patch
        from market_buyer.buyer_client import NegotiationOutcome
        def _fake_negotiate(*, seller_url, listing_id, **_kwargs):
            seen.append(listing_id)
            return NegotiationOutcome(
                status="exited", negotiation_id=None, agreed_price=None,
                rounds=0, reason="fake",
            )

        config = BuyConfig(
            registry_urls=["http://registry"],
            buyer_address="0xbuyer",
            buyer_private_key="0xpk",
            ssh_public_key="ssh-rsa ...",
            aggregation_policy="test_b_first",
        )
        constraints = BuyConstraints(
            duration_seconds=3600, initial_price=100, max_price=200,
        )

        with patch("market_buyer.buy_orchestrator.negotiate_with_seller", side_effect=_fake_negotiate):
            run_buy(
                config=config,
                constraints=constraints,
                create_escrow=lambda terms: pytest.fail("escrow shouldn't run on exit"),
                matches=[
                    _match("a", price=200, seller="http://a"),
                    _match("b", price=300, seller="http://b"),
                    _match("c", price=100, seller="http://c"),
                ],
            )

        # Policy moved 'b' to the front.
        assert seen[0] == "b"
        assert set(seen) == {"a", "b", "c"}
