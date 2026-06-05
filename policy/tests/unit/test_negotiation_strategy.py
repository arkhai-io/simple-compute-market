"""Unit tests for ``bisection_middleware`` and the chain runner.

The bisection logic is rule-based and deterministic; these tests pin
its accept / counter / exit behavior in both directions plus the
round-cap and stale-counter guards. Rounds carry full EscrowProposal
dicts; the negotiated scalar is ``proposal["fields"]["amount"]`` (an
absolute amount in base units — per-hour rates are a listing-broadcast
concept, never on the wire during negotiation).
"""

from __future__ import annotations

import pytest

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    accept_exact_listing_middleware,
    amount_bisection_middleware,
    bisection_middleware,
    load_negotiation_chain,
    register_negotiation_middleware,
    run_negotiation_chain,
)


_SKELETON = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "cd" * 20,
    "fields": {"token": "0x" + "ab" * 20},
    "expiration_unix": 1_800_000_000,
}


def _proposal_with_amount(amount: int | float) -> dict:
    """Test helper: a valid EscrowProposal dict with the given amount."""
    return {
        **_SKELETON,
        "fields": {**_SKELETON["fields"], "amount": int(round(amount))},
    }


def _native_token_proposal_with_amount(amount: int | float) -> dict:
    return {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"amount": int(round(amount))},
        "literal_fields": {},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
        "expiration_unix": 1_800_000_000,
    }


def _erc1155_proposal_with_amount(amount: int | float) -> dict:
    return {
        "chain_name": "anvil",
        "escrow_address": "0x" + "55" * 20,
        "fields": {
            "token": "0x" + "ab" * 20,
            "tokenId": 7,
            "amount": int(round(amount)),
        },
        "literal_fields": {"token": "0x" + "ab" * 20, "tokenId": 7},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
        "expiration_unix": 1_800_000_000,
    }


def _decision_amount(d: NegotiationDecision) -> int | None:
    if d.proposal is None:
        return None
    return d.proposal.get("fields", {}).get("amount")


# ---------------------------------------------------------------------------
# minimize direction (buyer-shape: peer's amount below ceiling = good)
# ---------------------------------------------------------------------------


def _decide_minimize(their, our_amount=100, history=None, max_rounds=10):
    history = list(history or [])
    if their is not None:
        history.append(NegotiationRound(
            round_number=len(history), sender="them", action="counter",
            proposal=_proposal_with_amount(their),
        ))
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=our_amount,
        our_escrow_proposal=_proposal_with_amount(our_amount),
        max_rounds=max_rounds,
    )
    return run_negotiation_chain([bisection_middleware], history, ctx)


def test_minimize_accepts_under_ceiling():
    d = _decide_minimize(their=90)
    assert d.action == "accept"
    assert _decision_amount(d) == 90


def test_minimize_accepts_at_convergence_boundary():
    d = _decide_minimize(their=100)
    assert d.action == "accept"


def test_minimize_counters_at_midpoint_when_reasonable():
    d = _decide_minimize(their=140)
    assert d.action == "counter"
    # midpoint(100, 140) = 120, but cap at our ceiling 100
    assert _decision_amount(d) == 100


def test_minimize_clamps_counter_to_ceiling():
    d = _decide_minimize(their=110)
    assert d.action == "counter"
    assert _decision_amount(d) == 100  # midpoint 105 > 100, clamp


def test_minimize_exits_when_peer_unreasonable():
    d = _decide_minimize(their=200)
    assert d.action == "exit"
    assert d.reason == "price_unreasonable"


# ---------------------------------------------------------------------------
# maximize direction (seller-shape: peer's amount above floor = good)
# ---------------------------------------------------------------------------


def _decide_maximize(their, our_amount=100, history=None):
    history = list(history or [])
    if their is not None:
        history.append(NegotiationRound(
            round_number=len(history), sender="them", action="counter",
            proposal=_proposal_with_amount(their),
        ))
    ctx = NegotiationContext(
        direction="maximize",
        our_reference_amount=our_amount,
        our_escrow_proposal=_proposal_with_amount(our_amount),
    )
    return run_negotiation_chain([bisection_middleware], history, ctx)


def test_maximize_accepts_above_floor():
    d = _decide_maximize(their=110)
    assert d.action == "accept"


def test_maximize_counters_at_midpoint():
    d = _decide_maximize(their=80)
    assert d.action == "counter"
    assert _decision_amount(d) == 90


def test_maximize_exits_when_peer_too_low():
    d = _decide_maximize(their=50)
    assert d.action == "exit"
    assert d.reason == "price_unreasonable"


# ---------------------------------------------------------------------------
# Round cap + stale guards (built into bisection_middleware)
# ---------------------------------------------------------------------------


def _our_counter(round_n, amount):
    return NegotiationRound(
        round_number=round_n, sender="us", action="counter",
        proposal=_proposal_with_amount(amount),
    )


def test_max_rounds_guard_fires():
    history = [_our_counter(i, 100) for i in range(10)]
    d = _decide_minimize(their=110, history=history, max_rounds=10)
    assert d.action == "exit"
    assert d.reason == "max_rounds"


def test_stale_guard_fires_on_two_identical_counters():
    history = [_our_counter(0, 100), _our_counter(1, 100)]
    d = _decide_minimize(their=110, history=history)
    assert d.action == "exit"
    assert d.reason == "stale_negotiation"


def test_stale_guard_does_not_fire_when_counters_differ():
    history = [_our_counter(0, 90), _our_counter(1, 95)]
    d = _decide_minimize(their=120, history=history)
    assert d.action != "exit" or d.reason != "stale_negotiation"


# ---------------------------------------------------------------------------
# First round (no peer amount yet) opens with our reference
# ---------------------------------------------------------------------------


def test_first_round_opens_with_our_reference():
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=100,
        our_escrow_proposal=_proposal_with_amount(100),
    )
    d = run_negotiation_chain([bisection_middleware], [], ctx)
    assert d.action == "counter"
    assert _decision_amount(d) == 100


# ---------------------------------------------------------------------------
# NegotiationDecision.to_dict shape
# ---------------------------------------------------------------------------


def test_to_dict_omits_none_fields():
    d = NegotiationDecision(action="accept")
    assert d.to_dict() == {"action": "accept"}

    p = _proposal_with_amount(42)
    d = NegotiationDecision(action="counter", proposal=p)
    assert d.to_dict() == {"action": "counter", "proposal": p}

    d = NegotiationDecision(action="accept", proposal=p, reason="convergence")
    assert d.to_dict() == {"action": "accept", "proposal": p, "reason": "convergence"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_load_negotiation_chain_resolves_bisection():
    chain = load_negotiation_chain(["bisection"])
    assert len(chain) == 1
    assert chain[0] is bisection_middleware


def test_load_negotiation_chain_resolves_accept_exact_listing():
    chain = load_negotiation_chain(["accept_exact_listing"])
    assert len(chain) == 1
    assert chain[0] is accept_exact_listing_middleware


@pytest.mark.parametrize(
    "name",
    ["erc20_bisection", "native_token_bisection", "erc1155_bisection"],
)
def test_load_negotiation_chain_resolves_amount_bisection_aliases(name):
    chain = load_negotiation_chain([name])
    assert len(chain) == 1
    assert chain[0] is amount_bisection_middleware


def test_native_token_bisection_uses_amount_field():
    history = [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="counter",
            proposal=_native_token_proposal_with_amount(80),
        )
    ]
    ctx = NegotiationContext(
        direction="maximize",
        our_reference_amount=100,
        our_escrow_proposal=_native_token_proposal_with_amount(100),
    )
    decision = run_negotiation_chain([amount_bisection_middleware], history, ctx)
    assert decision.action == "counter"
    assert _decision_amount(decision) == 90
    assert decision.proposal["literal_fields"] == {}
    assert decision.proposal["rates"] == [{"field": "amount", "per": "hour", "value": "100"}]


def test_erc1155_bisection_preserves_token_literals():
    history = [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="counter",
            proposal=_erc1155_proposal_with_amount(110),
        )
    ]
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=100,
        our_escrow_proposal=_erc1155_proposal_with_amount(100),
    )
    decision = run_negotiation_chain([amount_bisection_middleware], history, ctx)
    assert decision.action == "counter"
    assert _decision_amount(decision) == 100
    assert decision.proposal["literal_fields"] == {
        "token": "0x" + "ab" * 20,
        "tokenId": 7,
    }
    assert decision.proposal["fields"]["tokenId"] == 7


def test_register_negotiation_middleware_makes_it_loadable():
    @register_negotiation_middleware("test.fake")
    def _fake(history, context):
        return (
            NegotiationDecision(
                action="accept",
                proposal=_proposal_with_amount(context.our_reference_amount),
            ),
            context,
        )

    chain = load_negotiation_chain(["test.fake"])
    assert len(chain) == 1
    ctx = NegotiationContext(direction="maximize", our_reference_amount=42)
    d = run_negotiation_chain(chain, [], ctx)
    assert d.action == "accept"
    assert _decision_amount(d) == 42


def test_load_negotiation_chain_unknown_raises_with_actionable_message():
    with pytest.raises(KeyError) as exc_info:
        load_negotiation_chain(["does.not.exist"])
    msg = str(exc_info.value)
    assert "does.not.exist" in msg
    assert "bisection" in msg


@pytest.mark.parametrize("their,expected", [
    (100, "accept"), (101, "accept"), (105, "counter"), (151, "exit"),
])
def test_minimize_boundaries(their, expected):
    d = _decide_minimize(their=their)
    assert d.action == expected


# ---------------------------------------------------------------------------
# Chain runner
# ---------------------------------------------------------------------------


def test_chain_terminates_on_first_decision():
    """First middleware to return Some wins."""
    calls = []

    def mw_a(history, context):
        calls.append("a")
        return NegotiationDecision(action="exit", reason="from-a"), context

    def mw_b(history, context):
        calls.append("b")
        return NegotiationDecision(action="exit", reason="from-b"), context

    ctx = NegotiationContext(direction="maximize", our_reference_amount=100)
    d = run_negotiation_chain([mw_a, mw_b], [], ctx)
    assert d.reason == "from-a"
    assert calls == ["a"]


def test_chain_threads_context_when_middleware_defers():
    """A middleware returning None passes the (possibly updated) context onward."""
    def mw_record(history, context):
        context.intermediate["recorded"] = "by_first"
        return None, context

    def mw_terminal(history, context):
        return (
            NegotiationDecision(
                action="accept",
                proposal=_proposal_with_amount(context.our_reference_amount),
                reason=context.intermediate.get("recorded"),
            ),
            context,
        )

    ctx = NegotiationContext(direction="maximize", our_reference_amount=100)
    d = run_negotiation_chain([mw_record, mw_terminal], [], ctx)
    assert d.reason == "by_first"


def test_chain_exhausted_raises():
    """A chain that never decides is operator misconfiguration."""
    def mw_defer(history, context):
        return None, context

    ctx = NegotiationContext(direction="maximize", our_reference_amount=100)
    with pytest.raises(RuntimeError, match="exhausted"):
        run_negotiation_chain([mw_defer], [], ctx)
