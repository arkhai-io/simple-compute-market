from __future__ import annotations

from arkhai_vms_negotiation.policies import (
    buyer_counter_guard,
    round_zero_opening_guard,
)
from market_alkahest.schemas import EscrowProposal
from market_policy.negotiation_middleware import NegotiationContext, NegotiationRound


def _round_zero(proposal: EscrowProposal) -> list[NegotiationRound]:
    return [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=proposal.model_dump(),
        )
    ]


def _buyer_counter(proposal: dict | None) -> list[NegotiationRound]:
    return [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal=None,
        ),
        NegotiationRound(
            round_number=1,
            sender="us",
            action="counter",
            proposal=None,
        ),
        NegotiationRound(
            round_number=2,
            sender="them",
            action="counter",
            proposal=proposal,
        ),
    ]


def _context(listing: dict) -> NegotiationContext:
    return NegotiationContext(
        direction="maximize",
        our_reference_amount=1000,
        listing=listing,
    )


def _listing() -> dict:
    return {
        "listing_id": "L1",
        "max_duration_seconds": 7200,
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
            }
        ],
    }


def test_out_of_set_escrow_proposal_is_not_rejected_by_protocol_layer():
    listing = _listing()
    proposal = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "99" * 20,
        fields={"amount": 500},
        literal_fields={"token": "0x" + "22" * 20},
        rates=[],
        expiration_unix=1_800_000_000,
    )

    decision, context = round_zero_opening_guard(_round_zero(proposal), _context(listing))

    assert decision is None
    assert context.intermediate["accepted_escrow_proposal"] == proposal.model_dump()


def test_matching_escrow_proposal_is_canonicalized_from_listing():
    token = "0x" + "22" * 20
    listing_rates = [{"field": "amount", "per": "hour", "value": "1000"}]
    listing = {
        "listing_id": "L1",
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": token},
                "rates": listing_rates,
            }
        ],
    }
    proposal = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
        fields={"amount": 500},
        literal_fields={},
        rates=None,
        expiration_unix=1_800_000_000,
    )

    decision, context = round_zero_opening_guard(_round_zero(proposal), _context(listing))
    normalized = context.intermediate["accepted_escrow_proposal"]

    assert decision is None
    assert normalized["literal_fields"] == {"token": token}
    assert normalized["rates"] == [
        {"field": "amount", "per": "hour", "value": "1000"}
    ]


def test_round_zero_guard_rejects_non_positive_duration():
    proposal = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
        fields={"amount": 500},
        literal_fields={"token": "0x" + "22" * 20},
        rates=None,
        expiration_unix=1_800_000_000,
    )
    context = _context(_listing())
    context.intermediate["requested_duration_seconds"] = 0

    decision, _context_out = round_zero_opening_guard(_round_zero(proposal), context)

    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason == "compute_duration_invalid:duration_seconds must be > 0"


def test_round_zero_guard_rejects_duration_above_listing_max():
    proposal = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
        fields={"amount": 500},
        literal_fields={"token": "0x" + "22" * 20},
        rates=None,
        expiration_unix=1_800_000_000,
    )
    context = _context(_listing())
    context.intermediate["requested_duration_seconds"] = 7201

    decision, _context_out = round_zero_opening_guard(_round_zero(proposal), context)

    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason == "compute_duration_exceeds_listing_max:7201>7200"


def test_buyer_counter_guard_records_amount_and_canonical_proposal():
    pinned = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
        fields={"token": "0x" + "22" * 20, "amount": 500},
        literal_fields={"token": "0x" + "22" * 20},
        rates=None,
        expiration_unix=1_800_000_000,
    ).model_dump()
    counter = {**pinned, "fields": {"amount": 750}}
    context = _context(_listing())
    context.our_escrow_proposal = pinned

    decision, context = buyer_counter_guard(_buyer_counter(counter), context)

    assert decision is None
    assert context.intermediate["uses_scalar_amount"] is True
    assert context.intermediate["buyer_amount"] == 750
    # The canonical proposal carries the amount in its wire form: a
    # decimal-digit string, since a uint256 has no JSON number form and this
    # proposal is signed by both sides.
    assert context.intermediate["buyer_counter_proposal"]["fields"] == {
        "token": "0x" + "22" * 20,
        "amount": "750",
    }


def test_buyer_counter_guard_rejects_missing_scalar_amount():
    pinned = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
        fields={"token": "0x" + "22" * 20, "amount": 500},
        literal_fields={"token": "0x" + "22" * 20},
        rates=None,
        expiration_unix=1_800_000_000,
    ).model_dump()
    context = _context(_listing())
    context.our_escrow_proposal = pinned
    counter = {**pinned, "fields": {"token": "0x" + "22" * 20}}

    decision, _context_out = buyer_counter_guard(_buyer_counter(counter), context)

    assert decision is not None
    assert decision.action == "reject"
    assert decision.reason == "counter_missing_amount"


_OPTION_ID = "ab" * 32


def _selection_round(selection: dict) -> list[NegotiationRound]:
    return [
        NegotiationRound(
            round_number=0,
            sender="them",
            action="initial",
            proposal={"fields": {}, "settlement_selection": selection},
        )
    ]


def _option_listing() -> dict:
    return {
        "listing_id": "L1",
        "max_duration_seconds": 7200,
        "settlement_options": [
            {"option_id": _OPTION_ID, "mechanism": "arkhai.payments.v1", "asset": "USD/2"}
        ],
    }


def _selection(**extra) -> dict:
    return {
        "mechanism": "arkhai.payments.v1",
        "option_id": _OPTION_ID,
        "expiration_unix": 1_900_000_000,
        **extra,
    }


def test_selection_with_mechanism_params_is_accepted_with_them():
    """A payment selection carries the buyer's payer account as params."""
    params = {"payer_account": "11111111-1111-4111-8111-111111111111"}
    decision, context = round_zero_opening_guard(
        _selection_round(_selection(params=params)), _context(_option_listing())
    )
    assert decision is None
    assert context.intermediate["accepted_settlement_selection"]["params"] == params


def test_selection_with_empty_params_is_accepted():
    """A storefront serializes a parameterless selection with params set to None."""
    decision, _context_out = round_zero_opening_guard(
        _selection_round(_selection(params=None)), _context(_option_listing())
    )
    assert decision is None


def test_selection_with_unknown_fields_or_non_mapping_params_is_rejected():
    for selection in (_selection(amount="5"), _selection(params=["payer"])):
        decision, _context_out = round_zero_opening_guard(
            _selection_round(selection), _context(_option_listing())
        )
        assert decision is not None and decision.action == "reject"
        assert decision.reason == "invalid_settlement_selection:selection has invalid fields"
