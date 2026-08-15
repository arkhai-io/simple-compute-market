"""Selection-aware scalar participation in the shared scalar policies.

A published settlement option is the mechanism's cross-party declaration
of scalar participation: an ``amount`` rate means the deal is bargained
through ``fields.amount``; its absence means take-it-or-leave-it.
"""

from __future__ import annotations

from typing import Any

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationRound,
)
from market_policy.scalar_policies import (
    accept_exact_listing_middleware,
    buyer_counter_guard,
    option_uses_scalar_amount,
    proposal_uses_scalar_amount,
)

_SCALAR_OPTION = {
    "option_id": "aa" * 32,
    "mechanism": "fiat.stripe.v1",
    "asset": "usd",
    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    "params": {},
}
_NON_SCALAR_OPTION = {
    "option_id": "bb" * 32,
    "mechanism": "contact_exchange.v1",
    "asset": "introduction",
    "rates": [],
    "params": {"terms": "weekly rate negotiable on call"},
}
_LISTING = {"settlement_options": [_SCALAR_OPTION, _NON_SCALAR_OPTION]}


def _selection_proposal(
    option: dict[str, Any],
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "settlement_selection": {
            "mechanism": option["mechanism"],
            "option_id": option["option_id"],
            "expiration_unix": 1_900_000_000,
        },
        "fields": dict(fields or {}),
    }


def _context(reference_amount: float = 0.0) -> NegotiationContext:
    return NegotiationContext(
        direction="maximize",
        our_reference_amount=reference_amount,
        listing=dict(_LISTING),
    )


def test_option_scalar_declaration_reads_amount_rate() -> None:
    assert option_uses_scalar_amount(_SCALAR_OPTION) is True
    assert option_uses_scalar_amount(_NON_SCALAR_OPTION) is False
    assert option_uses_scalar_amount(None) is True


def test_selection_proposal_scalarness_follows_matched_option() -> None:
    assert (
        proposal_uses_scalar_amount(_LISTING, _selection_proposal(_SCALAR_OPTION))
        is True
    )
    assert (
        proposal_uses_scalar_amount(_LISTING, _selection_proposal(_NON_SCALAR_OPTION))
        is False
    )


def test_unmatched_selection_stays_scalar() -> None:
    unmatched = _selection_proposal(
        {"option_id": "cc" * 32, "mechanism": "contact_exchange.v1"}
    )
    assert proposal_uses_scalar_amount(_LISTING, unmatched) is True


def test_explicit_amount_is_scalar_regardless_of_option() -> None:
    proposal = _selection_proposal(_NON_SCALAR_OPTION, fields={"amount": 5})
    assert proposal_uses_scalar_amount(_LISTING, proposal) is True


def test_exact_accept_takes_non_scalar_selection_as_proposed() -> None:
    proposal = _selection_proposal(_NON_SCALAR_OPTION)
    history = [
        NegotiationRound(
            round_number=0, sender="them", action="initial", proposal=proposal
        )
    ]
    decision, _ = accept_exact_listing_middleware(history, _context())
    assert decision is not None
    assert decision.action == "accept"
    assert decision.proposal == proposal


def test_exact_accept_rejects_unlisted_selection() -> None:
    proposal = _selection_proposal(
        {"option_id": "cc" * 32, "mechanism": "contact_exchange.v1"}
    )
    history = [
        NegotiationRound(
            round_number=0, sender="them", action="initial", proposal=proposal
        )
    ]
    decision, _ = accept_exact_listing_middleware(history, _context())
    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason == "exact_listing:selection_not_in_options"


def test_exact_accept_holds_scalar_selection_to_reference_amount() -> None:
    history = [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=_selection_proposal(_SCALAR_OPTION, fields={"amount": 5}),
        )
    ]
    decision, _ = accept_exact_listing_middleware(history, _context(100.0))
    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason.startswith("exact_listing:amount_mismatch")

    history = [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=_selection_proposal(_SCALAR_OPTION, fields={"amount": 100}),
        )
    ]
    decision, _ = accept_exact_listing_middleware(history, _context(100.0))
    assert decision is not None
    assert decision.action == "accept"
    assert decision.proposal["fields"]["amount"] == 100


def test_buyer_counter_guard_tolerates_non_scalar_counter_without_amount() -> None:
    pinned = _selection_proposal(_NON_SCALAR_OPTION)
    context = _context()
    context.our_escrow_proposal = dict(pinned)
    history = [
        NegotiationRound(
            round_number=0, sender="us", action="initial", proposal=dict(pinned)
        ),
        NegotiationRound(
            round_number=1, sender="them", action="counter", proposal=dict(pinned)
        ),
    ]
    decision, out = buyer_counter_guard(history, context)
    assert decision is None
    assert out.intermediate["uses_scalar_amount"] is False
    assert out.intermediate["buyer_counter_proposal"] == pinned


def test_buyer_counter_guard_still_rejects_scalar_counter_without_amount() -> None:
    pinned = _selection_proposal(_SCALAR_OPTION)
    context = _context()
    context.our_escrow_proposal = dict(pinned)
    history = [
        NegotiationRound(
            round_number=0, sender="us", action="initial", proposal=dict(pinned)
        ),
        NegotiationRound(
            round_number=1, sender="them", action="counter", proposal=dict(pinned)
        ),
    ]
    decision, _ = buyer_counter_guard(history, context)
    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason == "counter_missing_amount"
