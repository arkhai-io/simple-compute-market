"""Unit tests for VM-domain negotiation policies."""

from __future__ import annotations

import pytest

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    load_negotiation_chain,
    run_negotiation_chain,
)
from domains.vms.negotiation.policies import (
    listed_price_middleware,
    accept_exact_listing_middleware,
    amount_bisection_middleware,
    bisection_middleware,
    make_escrow_kind_dispatch_middleware,
)


_SKELETON = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "cd" * 20,
    "fields": {"token": "0x" + "ab" * 20},
    "expiration_unix": 1_800_000_000,
}


def _proposal_with_amount(amount: int | float) -> dict:
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


def _decide_minimize(their, our_amount=100, history=None, max_rounds=10):
    history = list(history or [])
    if their is not None:
        history.append(NegotiationRound(
            round_number=len(history),
            sender="them",
            action="counter",
            proposal=_proposal_with_amount(their),
        ))
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=our_amount,
        our_escrow_proposal=_proposal_with_amount(our_amount),
        max_rounds=max_rounds,
    )
    return run_negotiation_chain([bisection_middleware], history, ctx)


def _decide_maximize(their, our_amount=100, history=None):
    history = list(history or [])
    if their is not None:
        history.append(NegotiationRound(
            round_number=len(history),
            sender="them",
            action="counter",
            proposal=_proposal_with_amount(their),
        ))
    ctx = NegotiationContext(
        direction="maximize",
        our_reference_amount=our_amount,
        our_escrow_proposal=_proposal_with_amount(our_amount),
    )
    return run_negotiation_chain([bisection_middleware], history, ctx)


def _our_counter(round_n, amount):
    return NegotiationRound(
        round_number=round_n,
        sender="us",
        action="counter",
        proposal=_proposal_with_amount(amount),
    )


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
    assert _decision_amount(d) == 100


def test_minimize_clamps_counter_to_ceiling():
    d = _decide_minimize(their=110)
    assert d.action == "counter"
    assert _decision_amount(d) == 100


def test_minimize_exits_when_peer_unreasonable():
    d = _decide_minimize(their=200)
    assert d.action == "exit"
    assert d.reason == "price_unreasonable"


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


def test_first_round_opens_with_our_reference():
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=100,
        our_escrow_proposal=_proposal_with_amount(100),
    )
    d = run_negotiation_chain([bisection_middleware], [], ctx)
    assert d.action == "counter"
    assert _decision_amount(d) == 100


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


def test_escrow_kind_dispatch_uses_family_policy(monkeypatch):
    from market_alkahest import alkahest

    monkeypatch.setattr(
        alkahest,
        "address_to_slot",
        lambda chain_name, address, *, config_path=None: (
            "native_token_escrow_obligation_nontierable"
        ),
    )
    dispatch = make_escrow_kind_dispatch_middleware({
        "native_token": ["native_token_bisection"],
    })
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
    decision = run_negotiation_chain([dispatch], history, ctx)
    assert decision.action == "counter"
    assert _decision_amount(decision) == 90
    assert ctx.intermediate["escrow_kind"] == "native_token_escrow_obligation_nontierable"
    assert ctx.intermediate["escrow_kind_policy_key"] == "native_token"


def test_escrow_kind_dispatch_rejects_unmapped_kind(monkeypatch):
    from market_alkahest import alkahest

    monkeypatch.setattr(
        alkahest,
        "address_to_slot",
        lambda chain_name, address, *, config_path=None: (
            "erc721_escrow_obligation_nontierable"
        ),
    )
    dispatch = make_escrow_kind_dispatch_middleware({
        "erc20": ["erc20_bisection"],
    })
    history = [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="counter",
            proposal=_erc1155_proposal_with_amount(100),
        )
    ]
    ctx = NegotiationContext(direction="maximize", our_reference_amount=100)
    decision = run_negotiation_chain([dispatch], history, ctx)
    assert decision.action == "reject"
    assert decision.reason == (
        "escrow_kind_dispatch:no_policy_for:erc721_escrow_obligation_nontierable"
    )


@pytest.mark.parametrize("their,expected", [
    (100, "accept"), (101, "accept"), (105, "counter"), (151, "exit"),
])
def test_minimize_boundaries(their, expected):
    d = _decide_minimize(their=their)
    assert d.action == expected


# ---------------------------------------------------------------------------
# listed_price — the buyer-side default terminal: pay the published price,
# accept within the bound, never counter.
# ---------------------------------------------------------------------------

def _decide_listed_price(their, our_amount=100, direction="minimize"):
    history = []
    if their is not None:
        history.append(NegotiationRound(
            round_number=0,
            sender="them",
            action="counter",
            proposal=_proposal_with_amount(their),
        ))
    ctx = NegotiationContext(
        direction=direction,
        our_reference_amount=our_amount,
        our_escrow_proposal=_proposal_with_amount(our_amount),
    )
    return run_negotiation_chain([listed_price_middleware], history, ctx)


def test_listed_price_accepts_at_the_bound():
    d = _decide_listed_price(their=100)
    assert d.action == "accept"
    assert _decision_amount(d) == 100


def test_listed_price_accepts_under_the_bound():
    d = _decide_listed_price(their=90)
    assert d.action == "accept"
    assert _decision_amount(d) == 90


def test_listed_price_never_counters_above_the_bound():
    d = _decide_listed_price(their=101)
    assert d.action == "exit"
    assert d.reason == "price_above_bound"


def test_listed_price_maximize_mirrors():
    assert _decide_listed_price(their=100, direction="maximize").action == "accept"
    assert _decide_listed_price(their=99, direction="maximize").action == "exit"


def test_listed_price_accepts_amountless_proposals():
    """Exact escrows carry no scalar amount; the pinned-shape guard
    upstream is the protection, the price policy just accepts."""
    history = [NegotiationRound(
        round_number=0, sender="them", action="counter",
        proposal={"chain_name": "anvil", "escrow_address": "0x" + "11" * 20,
                  "fields": {"token": "0x" + "22" * 20, "tokenId": "7"}},
    )]
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=100,
        our_escrow_proposal=None,
    )
    d = run_negotiation_chain([listed_price_middleware], history, ctx)
    assert d.action == "accept"
    assert d.reason == "listed_price_amountless"


def test_listed_price_restates_bound_when_nothing_from_them():
    d = _decide_listed_price(their=None)
    assert d.action == "counter"
    assert _decision_amount(d) == 100


def test_load_negotiation_chain_resolves_listed_price():
    chain = load_negotiation_chain(["listed_price"])
    assert chain == [listed_price_middleware]


def test_opening_amount_differs_from_bound_for_hagglers():
    """Round-0 runs through the chain: a haggler opens at
    our_opening_amount, not the bound (which would give the ceiling away)."""
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=100,
        our_opening_amount=50,
        our_escrow_proposal=_proposal_with_amount(0),
    )
    d = run_negotiation_chain([bisection_middleware], [], ctx)
    assert d.action == "counter"
    assert _decision_amount(d) == 50


def test_opening_leaves_exact_escrows_untouched():
    """A scalar policy never injects an amount into an exact-escrow shape."""
    exact = {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"token": "0x" + "22" * 20, "tokenId": "7"},
    }
    ctx = NegotiationContext(
        direction="minimize",
        our_reference_amount=100,
        our_escrow_proposal=exact,
    )
    d = run_negotiation_chain([listed_price_middleware], [], ctx)
    assert d.action == "counter"
    assert "amount" not in d.proposal["fields"]
