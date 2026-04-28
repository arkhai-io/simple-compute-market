"""Unit tests for the negotiation strategy interface + BisectionStrategy.

The bisection logic is rule-based and deterministic; these tests pin
its accept / counter / exit behavior in both directions plus the
round-cap and stale-counter guards.
"""

from __future__ import annotations

import pytest

from market_policy.negotiation_strategy import (
    BisectionStrategy,
    NegotiationDecision,
    NegotiationRound,
    NegotiationRoundInput,
    DEFAULT_MAX_ROUNDS,
    load_strategy,
    register_strategy,
)


# ---------------------------------------------------------------------------
# minimize direction (buyer-shape: peer's price below ceiling = good)
# ---------------------------------------------------------------------------


def _ri_minimize(their, our_price=100, history=None, max_rounds=DEFAULT_MAX_ROUNDS):
    return NegotiationRoundInput(
        direction="minimize",
        our_reference_price=our_price,
        their_proposed_price=their,
        history=history or [],
        max_rounds=max_rounds,
    )


def test_minimize_accepts_under_ceiling():
    d = BisectionStrategy().decide(_ri_minimize(their=90))
    assert d.action == "accept"
    assert d.price == 90


def test_minimize_accepts_at_convergence_boundary():
    d = BisectionStrategy().decide(_ri_minimize(their=100))
    assert d.action == "accept"


def test_minimize_counters_at_midpoint_when_reasonable():
    d = BisectionStrategy().decide(_ri_minimize(their=140))
    assert d.action == "counter"
    # midpoint(100, 140) = 120, but cap at our ceiling 100
    assert d.price == 100


def test_minimize_clamps_counter_to_ceiling():
    d = BisectionStrategy().decide(_ri_minimize(their=110))
    assert d.action == "counter"
    assert d.price == 100  # midpoint 105 > 100, clamp


def test_minimize_exits_when_peer_unreasonable():
    d = BisectionStrategy().decide(_ri_minimize(their=200))
    assert d.action == "exit"
    assert d.reason == "price_unreasonable"


# ---------------------------------------------------------------------------
# maximize direction (seller-shape: peer's price above floor = good)
# ---------------------------------------------------------------------------


def _ri_maximize(their, our_price=100, history=None):
    return NegotiationRoundInput(
        direction="maximize",
        our_reference_price=our_price,
        their_proposed_price=their,
        history=history or [],
    )


def test_maximize_accepts_above_floor():
    d = BisectionStrategy().decide(_ri_maximize(their=110))
    assert d.action == "accept"


def test_maximize_counters_at_midpoint():
    d = BisectionStrategy().decide(_ri_maximize(their=80))
    assert d.action == "counter"
    assert d.price == 90


def test_maximize_exits_when_peer_too_low():
    d = BisectionStrategy().decide(_ri_maximize(their=50))
    assert d.action == "exit"
    assert d.reason == "price_unreasonable"


# ---------------------------------------------------------------------------
# Round cap + stale guards
# ---------------------------------------------------------------------------


def _our_counter(round_n, price):
    return NegotiationRound(
        round_number=round_n, sender="us", action="counter", price=price,
    )


def test_max_rounds_guard_fires():
    history = [_our_counter(i, 100) for i in range(10)]
    d = BisectionStrategy().decide(_ri_minimize(their=110, history=history, max_rounds=10))
    assert d.action == "exit"
    assert d.reason == "max_rounds"


def test_stale_guard_fires_on_two_identical_counters():
    history = [_our_counter(0, 100), _our_counter(1, 100)]
    d = BisectionStrategy().decide(_ri_minimize(their=110, history=history))
    assert d.action == "exit"
    assert d.reason == "stale_negotiation"


def test_stale_guard_does_not_fire_when_counters_differ():
    history = [_our_counter(0, 90), _our_counter(1, 95)]
    d = BisectionStrategy().decide(_ri_minimize(their=120, history=history))
    assert d.action != "exit" or d.reason != "stale_negotiation"


# ---------------------------------------------------------------------------
# First round (no peer price yet) opens with our reference
# ---------------------------------------------------------------------------


def test_first_round_opens_with_our_reference():
    d = BisectionStrategy().decide(NegotiationRoundInput(
        direction="minimize",
        our_reference_price=100,
        their_proposed_price=None,
    ))
    assert d.action == "counter"
    assert d.price == 100


# ---------------------------------------------------------------------------
# NegotiationDecision.to_dict shape
# ---------------------------------------------------------------------------


def test_to_dict_omits_none_fields():
    d = NegotiationDecision(action="accept")
    assert d.to_dict() == {"action": "accept"}

    d = NegotiationDecision(action="counter", price=42)
    assert d.to_dict() == {"action": "counter", "price": 42}

    d = NegotiationDecision(action="accept", price=42, reason="convergence")
    assert d.to_dict() == {"action": "accept", "price": 42, "reason": "convergence"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_load_strategy_resolves_bisection():
    s = load_strategy("bisection")
    assert isinstance(s, BisectionStrategy)


def test_load_strategy_default_is_rl_or_clear_error():
    """Default strategy is 'rl' — when not registered, raises with an
    actionable message naming the [rl] extras."""
    try:
        s = load_strategy()  # name=None → DEFAULT_STRATEGY ("rl")
    except KeyError as exc:
        assert "rl" in str(exc).lower()
        return
    # If rl IS registered (the torch strategy module imported), that's
    # also fine — confirm we got something back.
    assert s is not None


def test_register_strategy_makes_it_loadable():
    class Fake:
        def decide(self, ri):
            return NegotiationDecision(action="accept", price=ri.our_reference_price)

    register_strategy("test.fake", lambda cfg: Fake(**cfg))
    s = load_strategy("test.fake")
    assert isinstance(s, Fake)


def test_load_strategy_unknown_raises_with_actionable_message():
    with pytest.raises(KeyError) as exc_info:
        load_strategy("does.not.exist")
    msg = str(exc_info.value)
    assert "does.not.exist" in msg
    assert "bisection" in msg  # available list includes bisection


@pytest.mark.parametrize("their,expected", [
    (100, "accept"), (101, "accept"), (105, "counter"), (151, "exit"),
])
def test_minimize_boundaries(their, expected):
    d = BisectionStrategy().decide(_ri_minimize(their=their))
    assert d.action == expected
