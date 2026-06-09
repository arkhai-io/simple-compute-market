from __future__ import annotations

from market_storefront.utils.sync_negotiation import _validate_escrow_proposal
from market_alkahest.schemas import EscrowProposal


def test_out_of_set_escrow_proposal_is_not_rejected_by_protocol_layer():
    listing = {
        "listing_id": "L1",
        "accepted_escrows": [
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
            }
        ],
    }
    proposal = EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "99" * 20,
        fields={"amount": 500},
        literal_fields={"token": "0x" + "22" * 20},
        rates=[],
        expiration_unix=1_800_000_000,
    )

    normalized = _validate_escrow_proposal(proposal=proposal, listing=listing)

    assert normalized == proposal


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

    normalized = _validate_escrow_proposal(proposal=proposal, listing=listing)

    assert normalized is not None
    assert normalized.literal_fields == {"token": token}
    assert [rate.model_dump() for rate in (normalized.rates or [])] == [
        {"field": "amount", "per": "hour", "value": "1000"}
    ]
