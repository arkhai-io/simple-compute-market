"""Tests for the across-seller aggregation policy registry.

The new protocol is ``(candidates, negotiate) -> (match, outcome) | None``
— the policy owns ordering, fan-out, and selection. These tests drive
the built-ins with a recording negotiator so we can assert the order
in which candidates were negotiated with, plus pluggability via
``register_aggregation_policy``.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from market_buyer.aggregation import (
    DEFAULT_POLICY_NAME,
    NegotiateFn,
    gather_outcomes,
    list_aggregation_policies,
    load_aggregation_policy,
    register_aggregation_policy,
)
from market_buyer.buyer_client import NegotiationOutcome


def _match(listing_id: str, *, price: int | None = None, seller: str = "http://s") -> dict[str, Any]:
    demand: dict[str, Any] = {"token": "MOCK"}
    if price is not None:
        demand["amount"] = price
    return {
        "listing_id": listing_id,
        "seller": seller,
        "demand_resource": demand,
    }


def _recorder(*, agree_at: int | None = None) -> tuple[list[str], NegotiateFn]:
    """Build a fake negotiate callback that records call order.

    ``agree_at``: index into the call-order list at which to return
    ``status="agreed"``. None means everyone exits (no agreement).
    """
    seen: list[str] = []

    async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
        seen.append(match["listing_id"])
        if agree_at is not None and (len(seen) - 1) == agree_at:
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=match.get("demand_resource", {}).get("amount", 0),
            )
        return NegotiationOutcome(
            status="exited",
            negotiation_id=None,
            reason="fake",
        )

    return seen, _negotiate


def _drive(policy, candidates, negotiate):
    return asyncio.run(policy(candidates, negotiate))


# ---------------------------------------------------------------------------
# Built-in policies — ordering verified via call-order recording
# ---------------------------------------------------------------------------


class TestCheapestFirst:
    def test_negotiates_in_price_ascending_order(self):
        policy = load_aggregation_policy("cheapest_first")
        seen, neg = _recorder()
        matches = [_match("a", price=300), _match("b", price=100), _match("c", price=200)]
        _drive(policy, matches, neg)
        assert seen == ["b", "c", "a"]

    def test_first_agreed_wins_and_stops_iteration(self):
        policy = load_aggregation_policy("cheapest_first")
        seen, neg = _recorder(agree_at=0)
        matches = [_match("a", price=300), _match("b", price=100), _match("c", price=200)]
        result = _drive(policy, matches, neg)
        assert seen == ["b"]
        assert result is not None
        winning_match, outcome = result
        assert winning_match["listing_id"] == "b"
        assert outcome.agreed_price == 100

    def test_priceless_listings_sort_to_end(self):
        policy = load_aggregation_policy("cheapest_first")
        seen, neg = _recorder()
        matches = [
            _match("priceless1"),
            _match("priced", price=500),
            _match("priceless2", price=0),
        ]
        _drive(policy, matches, neg)
        assert seen[0] == "priced"
        assert set(seen[1:]) == {"priceless1", "priceless2"}

    def test_serialised_demand_string_is_parsed(self):
        """Registry sometimes returns demand_resource as a JSON string."""
        policy = load_aggregation_policy("cheapest_first")
        seen, neg = _recorder()
        matches = [
            {"listing_id": "a", "demand_resource": json.dumps({"amount": 200})},
            {"listing_id": "b", "demand_resource": json.dumps({"amount": 100})},
        ]
        _drive(policy, matches, neg)
        assert seen == ["b", "a"]

    def test_default_is_cheapest_first(self):
        assert DEFAULT_POLICY_NAME == "cheapest_first"


class TestRegistryOrder:
    def test_negotiates_in_registry_order(self):
        policy = load_aggregation_policy("registry_order")
        seen, neg = _recorder()
        matches = [_match("a", price=300), _match("b", price=100)]
        _drive(policy, matches, neg)
        assert seen == ["a", "b"]


class TestRandomShuffle:
    def test_negotiates_full_set(self):
        policy = load_aggregation_policy("random_shuffle")
        seen, neg = _recorder()
        matches = [_match(str(i), price=i * 10) for i in range(10)]
        _drive(policy, matches, neg)
        assert set(seen) == {m["listing_id"] for m in matches}
        assert len(seen) == len(matches)

    def test_does_not_mutate_input_list(self):
        policy = load_aggregation_policy("random_shuffle")
        original = [_match(str(i)) for i in range(5)]
        snapshot = [m["listing_id"] for m in original]
        _, neg = _recorder()
        _drive(policy, original, neg)
        assert [m["listing_id"] for m in original] == snapshot


class TestPricelessLast:
    def test_priced_first_then_priceless(self):
        policy = load_aggregation_policy("priceless_last")
        seen, neg = _recorder()
        matches = [
            _match("priceless1"),
            _match("priced_high", price=500),
            _match("priceless2"),
            _match("priced_low", price=100),
        ]
        _drive(policy, matches, neg)
        assert seen == ["priced_low", "priced_high", "priceless1", "priceless2"]


class TestBestPrice:
    def test_picks_lowest_agreed_across_all(self):
        """All candidates negotiated in parallel; lowest agreed_price wins.

        Distinct from cheapest_first: the *advertised* prices don't
        determine the winner, only the negotiated outcome does.
        """
        policy = load_aggregation_policy("best_price")

        async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
            agreed = {"a": 80, "b": 60, "c": 90}[match["listing_id"]]
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=agreed,
            )

        matches = [
            _match("a", price=50),   # cheapest advertised, but agrees high
            _match("b", price=70),
            _match("c", price=100),  # most expensive advertised, but doesn't matter
        ]
        result = _drive(policy, matches, _negotiate)
        assert result is not None
        winner, outcome = result
        assert winner["listing_id"] == "b"
        assert outcome.agreed_price == 60

    def test_none_when_no_candidate_agrees(self):
        policy = load_aggregation_policy("best_price")
        seen, neg = _recorder()
        result = _drive(policy, [_match("a"), _match("b")], neg)
        assert result is None
        assert set(seen) == {"a", "b"}

    def test_swallows_per_candidate_exceptions(self):
        """One flaky seller doesn't kill the comparison."""
        policy = load_aggregation_policy("best_price")

        async def _flaky(match: dict[str, Any]) -> NegotiationOutcome:
            if match["listing_id"] == "broken":
                raise RuntimeError("seller down")
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=50,
            )

        matches = [_match("broken"), _match("good"), _match("alsogood")]
        result = _drive(policy, matches, _flaky)
        assert result is not None
        winner, _ = result
        assert winner["listing_id"] in {"good", "alsogood"}


# ---------------------------------------------------------------------------
# Pluggability
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_unknown_policy_raises(self):
        with pytest.raises(ValueError, match="Unknown across-seller aggregation policy"):
            load_aggregation_policy("does_not_exist")

    def test_none_returns_default(self):
        assert load_aggregation_policy(None) is load_aggregation_policy("cheapest_first")

    def test_register_custom_policy(self):
        @register_aggregation_policy("test_reverse")
        async def _reverse(matches, negotiate: NegotiateFn):
            for m in reversed(matches):
                outcome = await negotiate(m)
                if outcome.status == "agreed":
                    return (m, outcome)
            return None

        assert "test_reverse" in list_aggregation_policies()
        seen, neg = _recorder()
        _drive(load_aggregation_policy("test_reverse"),
               [_match("a"), _match("b"), _match("c")], neg)
        assert seen == ["c", "b", "a"]

    def test_register_overwrites(self):
        @register_aggregation_policy("test_double")
        async def _v1(matches, negotiate):
            return None

        @register_aggregation_policy("test_double")
        async def _v2(matches, negotiate):
            if matches:
                outcome = await negotiate(matches[-1])
                return (matches[-1], outcome) if outcome.status == "agreed" else None
            return None

        seen, neg = _recorder(agree_at=0)
        _drive(load_aggregation_policy("test_double"),
               [_match("a"), _match("b"), _match("c")], neg)
        assert seen == ["c"]


class TestHelpers:
    def test_gather_outcomes_returns_pairs(self):
        async def _ok(match: dict[str, Any]) -> NegotiationOutcome:
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=50,
            )

        results = asyncio.run(gather_outcomes(_ok, [_match("a"), _match("b")]))
        assert len(results) == 2
        ids = {c["listing_id"] for c, _ in results}
        assert ids == {"a", "b"}
        assert all(isinstance(r, NegotiationOutcome) for _, r in results)
