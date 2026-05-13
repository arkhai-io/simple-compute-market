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

    def test_default_is_best_price(self):
        # Comparison shopping over cross-seller parallel negotiation is
        # the headline reason the orchestrator owns this seam. The
        # sequential alternatives are still available, but only need
        # to be opted into.
        assert DEFAULT_POLICY_NAME == "best_price"


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


class TestFastestAgreed:
    def test_returns_first_to_agree_regardless_of_advertised_order(self):
        """`fast` agrees immediately; `slow` would agree later but never
        gets a chance because the race ends first."""
        policy = load_aggregation_policy("fastest_agreed")

        async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
            if match["listing_id"] == "fast":
                # Yield once so the event loop schedules both tasks
                # before either resolves; without this asyncio may
                # short-circuit on the first task it scheduled.
                await asyncio.sleep(0)
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id="neg-fast",
                    agreed_price=100,
                )
            # `slow` never finishes within the race; the policy must
            # not block on it.
            await asyncio.sleep(10)
            return NegotiationOutcome(
                status="agreed",
                negotiation_id="neg-slow",
                agreed_price=50,
            )

        # Order `slow` first to make sure ordering doesn't decide.
        result = _drive(policy, [_match("slow"), _match("fast")], _negotiate)
        assert result is not None
        winner, outcome = result
        assert winner["listing_id"] == "fast"
        assert outcome.agreed_price == 100

    def test_returns_none_when_no_candidate_agrees(self):
        policy = load_aggregation_policy("fastest_agreed")

        async def _all_exit(_match: dict[str, Any]) -> NegotiationOutcome:
            return NegotiationOutcome(
                status="exited", negotiation_id=None, reason="no_deal",
            )

        result = _drive(policy, [_match("a"), _match("b"), _match("c")], _all_exit)
        assert result is None

    def test_continues_racing_past_exiters(self):
        """An exiting seller doesn't win the race — the policy keeps
        waiting for an agreement from the survivors."""
        policy = load_aggregation_policy("fastest_agreed")

        async def _mixed(match: dict[str, Any]) -> NegotiationOutcome:
            if match["listing_id"] == "exiter":
                # Finishes immediately, but with status=exited, so it
                # must NOT be picked as the winner.
                return NegotiationOutcome(
                    status="exited", negotiation_id=None, reason="no",
                )
            await asyncio.sleep(0)
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=50,
            )

        result = _drive(policy, [_match("exiter"), _match("good")], _mixed)
        assert result is not None
        winner, _ = result
        assert winner["listing_id"] == "good"

    def test_swallows_exceptions_and_keeps_racing(self):
        policy = load_aggregation_policy("fastest_agreed")

        async def _flaky(match: dict[str, Any]) -> NegotiationOutcome:
            if match["listing_id"] == "broken":
                raise RuntimeError("seller down")
            await asyncio.sleep(0)
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=50,
            )

        result = _drive(policy, [_match("broken"), _match("good")], _flaky)
        assert result is not None
        winner, _ = result
        assert winner["listing_id"] == "good"

    def test_cancels_pending_tasks_after_winner(self):
        """Once a winner emerges, the still-pending negotiations must
        be cancelled — otherwise we'd waste compute (and on the real
        network, leave dangling state on losing sellers)."""
        policy = load_aggregation_policy("fastest_agreed")
        slow_completed = 0

        async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
            nonlocal slow_completed
            if match["listing_id"] == "fast":
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id="neg-fast",
                    agreed_price=100,
                )
            # If the policy doesn't cancel, this sleep runs to
            # completion and increments the counter.
            await asyncio.sleep(0.1)
            slow_completed += 1
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=50,
            )

        matches = [_match("fast"), _match("slow1"), _match("slow2")]
        result = _drive(policy, matches, _negotiate)
        assert result is not None
        winner, _ = result
        assert winner["listing_id"] == "fast"
        # Both slow tasks must have been cancelled before reaching the
        # increment — otherwise the race policy is leaking work.
        assert slow_completed == 0


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


class TestBestPriceTimeoutResolver:
    """Direct tests of ``_resolve_best_price_timeout`` so the policy
    body can assume the value is either a positive float or None."""

    def _with_cfg(self, raw):
        from unittest.mock import patch

        from market_buyer import aggregation as agg

        # Patch the config load to return a single key. get_dotted
        # then traverses it normally — so we exercise the real
        # parsing path, not a stub.
        cfg = {"buyer": {"aggregation": {"best_price_timeout": raw}}}
        with patch.object(agg, "_load_buyer_config", lambda: cfg):
            return agg._resolve_best_price_timeout()

    def test_unset_returns_none(self):
        from market_buyer import aggregation as agg
        from unittest.mock import patch
        with patch.object(agg, "_load_buyer_config", lambda: {}):
            assert agg._resolve_best_price_timeout() is None

    def test_positive_float_passes_through(self):
        assert self._with_cfg(30.0) == 30.0
        assert self._with_cfg(0.5) == 0.5

    def test_positive_int_coerces_to_float(self):
        assert self._with_cfg(30) == 30.0

    def test_string_numeric_coerces(self):
        # TOML normally types numerics, but if the user accidentally
        # quotes the value we still try to parse it before giving up.
        assert self._with_cfg("15") == 15.0

    def test_zero_and_negative_treated_as_unset(self):
        assert self._with_cfg(0) is None
        assert self._with_cfg(-5) is None

    def test_non_numeric_treated_as_unset(self):
        assert self._with_cfg("forever") is None
        assert self._with_cfg([1, 2]) is None


class TestBestPriceTimeout:
    """The optional `[buyer.aggregation] best_price_timeout` knob.

    Patches the resolver directly rather than touching real TOML —
    keeps the tests self-contained and avoids buyer-config singleton
    state.
    """

    def test_returns_best_of_completed_when_slow_seller_misses_deadline(self):
        """Slow seller's hypothetical lower price doesn't count if it
        hasn't agreed by the deadline. The best of the in-time
        completions wins."""
        from unittest.mock import patch

        from market_buyer import aggregation as agg

        slow_completed = 0

        async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
            nonlocal slow_completed
            if match["listing_id"] == "fast_expensive":
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id="neg-fast-expensive",
                    agreed_price=100,
                )
            if match["listing_id"] == "fast_cheap":
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id="neg-fast-cheap",
                    agreed_price=70,
                )
            # `slow_cheapest` would have won on price had it agreed in
            # time, but it sleeps past the 50ms budget.
            await asyncio.sleep(0.5)
            slow_completed += 1
            return NegotiationOutcome(
                status="agreed",
                negotiation_id="neg-slow",
                agreed_price=10,
            )

        matches = [
            _match("fast_expensive"),
            _match("fast_cheap"),
            _match("slow_cheapest"),
        ]
        with patch.object(agg, "_resolve_best_price_timeout", lambda: 0.05):
            result = _drive(agg.load_aggregation_policy("best_price"), matches, _negotiate)

        assert result is not None
        winner, outcome = result
        assert winner["listing_id"] == "fast_cheap"
        assert outcome.agreed_price == 70
        # The slow seller's task must have been cancelled — if not,
        # the test would have either slept the full 500ms or recorded
        # a completion.
        assert slow_completed == 0

    def test_returns_none_when_nobody_agrees_in_time(self):
        from unittest.mock import patch

        from market_buyer import aggregation as agg

        async def _all_slow(_m: dict[str, Any]) -> NegotiationOutcome:
            await asyncio.sleep(0.5)
            return NegotiationOutcome(
                status="agreed", negotiation_id="x", agreed_price=10,
            )

        with patch.object(agg, "_resolve_best_price_timeout", lambda: 0.05):
            result = _drive(
                agg.load_aggregation_policy("best_price"),
                [_match("a"), _match("b")],
                _all_slow,
            )
        assert result is None

    def test_unset_timeout_waits_for_all(self):
        """With no timeout configured, behavior is unchanged: the
        slowest seller's outcome still counts toward the comparison."""
        from unittest.mock import patch

        from market_buyer import aggregation as agg

        async def _negotiate(match: dict[str, Any]) -> NegotiationOutcome:
            if match["listing_id"] == "slow_cheapest":
                # Small but real delay so the test exercises the wait.
                await asyncio.sleep(0.01)
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id="neg-slow",
                    agreed_price=10,
                )
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=f"neg-{match['listing_id']}",
                agreed_price=100,
            )

        with patch.object(agg, "_resolve_best_price_timeout", lambda: None):
            result = _drive(
                agg.load_aggregation_policy("best_price"),
                [_match("fast"), _match("slow_cheapest")],
                _negotiate,
            )
        assert result is not None
        winner, outcome = result
        assert winner["listing_id"] == "slow_cheapest"
        assert outcome.agreed_price == 10


# ---------------------------------------------------------------------------
# Pluggability
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_unknown_policy_raises(self):
        with pytest.raises(ValueError, match="Unknown across-seller aggregation policy"):
            load_aggregation_policy("does_not_exist")

    def test_none_returns_default(self):
        assert load_aggregation_policy(None) is load_aggregation_policy("best_price")

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
