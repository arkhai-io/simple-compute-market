from __future__ import annotations

from domains.vms.negotiation.policies import round_zero_opening_guard
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
