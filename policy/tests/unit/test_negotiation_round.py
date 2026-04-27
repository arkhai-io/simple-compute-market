"""Unit tests for the synchronous negotiation decision function.

`decide_response` is a pure function: given strategy + our_price + their
proposed price + our previous counters, return a SellerDecision. No DB,
no registry, no async. Makes the policy behaviour trivially testable
without spinning up the event pipeline.
"""

from __future__ import annotations

import pytest

from market_policy.negotiation_round import (
    DEFAULT_MAX_ROUNDS,
    SellerDecision,
    decide_buyer_response,
    decide_response,
)


# ---------------------------------------------------------------------------
# minimize strategy (we're selling compute; peer is paying tokens)
# ---------------------------------------------------------------------------


def test_minimize_accepts_within_convergence():
    """Peer offered ≤ (our_price × 1.01) → accept at their price."""
    d = decide_response(
        strategy="minimize",
        our_price=100,
        their_proposed_price=100,
        our_previous_counters=[],
    )
    assert d.action == "accept"
    assert d.price == 100
    assert d.reason == "convergence"


def test_minimize_counters_at_midpoint_when_reasonable():
    """Peer in (our_price, our_price × 1.5] → counter at midpoint."""
    d = decide_response(
        strategy="minimize",
        our_price=100,
        their_proposed_price=140,
        our_previous_counters=[],
    )
    assert d.action == "counter"
    assert d.price == 120  # (100 + 140) // 2


def test_minimize_exits_when_peer_too_high():
    """Peer > our_price × 1.5 → exit."""
    d = decide_response(
        strategy="minimize",
        our_price=100,
        their_proposed_price=200,
        our_previous_counters=[],
    )
    assert d.action == "exit"
    assert d.reason == "price_unreasonable"


# ---------------------------------------------------------------------------
# maximize strategy (we're buying compute; peer is offering compute for tokens)
# ---------------------------------------------------------------------------


def test_maximize_accepts_within_convergence():
    """Peer offered ≥ (our_price × 0.99) → accept."""
    d = decide_response(
        strategy="maximize",
        our_price=100,
        their_proposed_price=100,
        our_previous_counters=[],
    )
    assert d.action == "accept"
    assert d.price == 100


def test_maximize_counters_at_midpoint():
    """Peer in [our_price / 1.5, our_price) → counter at midpoint."""
    d = decide_response(
        strategy="maximize",
        our_price=100,
        their_proposed_price=80,
        our_previous_counters=[],
    )
    assert d.action == "counter"
    assert d.price == 90


def test_maximize_exits_when_peer_too_low():
    """Peer < our_price / 1.5 → exit."""
    d = decide_response(
        strategy="maximize",
        our_price=100,
        their_proposed_price=50,
        our_previous_counters=[],
    )
    assert d.action == "exit"
    assert d.reason == "price_unreasonable"


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------


def test_max_rounds_guard_fires_exit():
    """Having already countered MAX_ROUNDS times → exit regardless of price."""
    history = [100] * DEFAULT_MAX_ROUNDS
    d = decide_response(
        strategy="minimize",
        our_price=100,
        their_proposed_price=100,  # would otherwise accept
        our_previous_counters=history,
    )
    assert d.action == "exit"
    assert d.reason == "max_rounds"


def test_stale_guard_fires_when_last_two_counters_equal():
    """Our last two counters were identical → exit as stuck."""
    d = decide_response(
        strategy="minimize",
        our_price=100,
        their_proposed_price=130,  # would normally counter at 115
        our_previous_counters=[115, 115],
    )
    assert d.action == "exit"
    assert d.reason == "stale_negotiation"


def test_stale_guard_does_not_fire_when_counters_differ():
    """Last two counters diverge → keep going."""
    d = decide_response(
        strategy="minimize",
        our_price=100,
        their_proposed_price=130,
        our_previous_counters=[120, 115],
    )
    assert d.action == "counter"


# ---------------------------------------------------------------------------
# unknown strategy
# ---------------------------------------------------------------------------


def test_unknown_strategy_rejects():
    d = decide_response(
        strategy="barter",
        our_price=100,
        their_proposed_price=100,
        our_previous_counters=[],
    )
    assert d.action == "reject"
    assert d.reason and "unknown_strategy" in d.reason


# ---------------------------------------------------------------------------
# SellerDecision.to_dict shape
# ---------------------------------------------------------------------------


def test_to_dict_omits_none_fields():
    assert SellerDecision(action="counter", price=42).to_dict() == {
        "action": "counter", "price": 42,
    }
    assert SellerDecision(action="exit", reason="max_rounds").to_dict() == {
        "action": "exit", "reason": "max_rounds",
    }
    assert SellerDecision(
        action="accept", price=42, reason="convergence",
    ).to_dict() == {
        "action": "accept", "price": 42, "reason": "convergence",
    }


@pytest.mark.parametrize("price,expected", [(100, "accept"), (101, "accept"), (105, "counter"), (151, "exit")])
def test_minimize_boundary(price, expected):
    d = decide_response(
        strategy="minimize",
        our_price=100,
        their_proposed_price=price,
        our_previous_counters=[],
    )
    assert d.action == expected


# ---------------------------------------------------------------------------
# decide_buyer_response — buyer-side variant with max-price cap
# ---------------------------------------------------------------------------


def test_buyer_accept_when_seller_price_under_ceiling():
    move = decide_buyer_response(
        seller_counter_price=90, max_price=100, our_previous_counters=[],
    )
    assert move.action == "accept"
    assert move.price == 90


def test_buyer_accept_at_convergence_boundary():
    move = decide_buyer_response(
        seller_counter_price=100, max_price=100, our_previous_counters=[],
    )
    assert move.action == "accept"
    assert move.price == 100


def test_buyer_counter_caps_at_max_price():
    """Seller asks 140, ceiling 100 → midpoint 120, clamped to 100."""
    move = decide_buyer_response(
        seller_counter_price=140, max_price=100, our_previous_counters=[],
    )
    assert move.action == "counter"
    assert move.price == 100


def test_buyer_counter_caps_when_seller_only_slightly_over():
    """Seller asks 110, ceiling 100 → midpoint 105, clamped to 100."""
    move = decide_buyer_response(
        seller_counter_price=110, max_price=100, our_previous_counters=[],
    )
    assert move.action == "counter"
    assert move.price == 100


def test_buyer_exit_when_seller_price_unreasonable():
    """Seller asks 200, ceiling 100 → exit (ratio > 1.5)."""
    move = decide_buyer_response(
        seller_counter_price=200, max_price=100, our_previous_counters=[],
    )
    assert move.action == "exit"
    assert move.reason == "price_unreasonable"


def test_buyer_max_rounds_exits():
    move = decide_buyer_response(
        seller_counter_price=100, max_price=100,
        our_previous_counters=[50] * 10, max_rounds=10,
    )
    assert move.action == "exit"
    assert move.reason == "max_rounds"


def test_buyer_stale_counter_guard_fires():
    move = decide_buyer_response(
        seller_counter_price=140, max_price=100,
        our_previous_counters=[100, 100],
    )
    assert move.action == "exit"
    assert move.reason == "stale_negotiation"
