"""A native-token escrow built from a listing entry verifies against the chain.

Runs the proposal a seller derives from its accepted escrow entry through the
settlement verifier, with the chain read replaced by the SDK's own decoded
obligation type, against the development chain's address book.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from alkahest_py import NativeTokenEscrowObligationData
from market_alkahest.alkahest import (
    NativeTokenDefaultEscrowCodec,
    encode_recipient_demand,
    get_recipient_arbiter,
)
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.escrow_verification import (
    EscrowVerificationError,
    verify_escrow_for_settlement,
)
from market_alkahest.proposals import escrow_proposal_from_accepted_entry
from market_alkahest.schemas import EscrowProposal

_CHAIN = "anvil"
_ADDRESSES = str(anvil_address_book_path())
# Anvil's deterministic development account #2; never use it on a public network.
_SELLER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
_AMOUNT = 9_500
_EXPIRATION = 1_900_000_000


def _arbiter() -> str:
    return get_recipient_arbiter(_CHAIN, config_path=_ADDRESSES)


def _native_proposal() -> EscrowProposal:
    entry = {
        "chain_name": _CHAIN,
        "escrow_address": NativeTokenDefaultEscrowCodec().resolve_address(
            _CHAIN, config_path=_ADDRESSES,
        ),
        "literal_fields": {},
        "rates": [{"field": "amount", "per": "hour", "value": str(_AMOUNT)}],
    }
    listing = {
        "demands": [{
            "chain_name": _CHAIN,
            "arbiter": _arbiter().lower(),
            "demand_data": {"recipient": _SELLER.lower()},
        }],
    }
    return escrow_proposal_from_accepted_entry(
        listing=listing, entry=entry, expiration_unix=_EXPIRATION,
    )


async def _verify(proposal: EscrowProposal) -> int:
    # The SDK decodes a native escrow's amount as a decimal string.
    data = NativeTokenEscrowObligationData(
        _arbiter(), encode_recipient_demand(_SELLER), str(_AMOUNT),
    )
    attestation = SimpleNamespace(revocation_time=0, expiration_time=_EXPIRATION)

    async def _get_obligation(client, uid):
        return {"attestation": attestation, "data": data}

    return await verify_escrow_for_settlement(
        escrow_uid="0x" + "ab" * 32,
        seller_wallet=_SELLER,
        agreed_price=_AMOUNT,
        agreed_duration_seconds=3600,
        listing={},
        alkahest_client=object(),
        chain_name=_CHAIN,
        alkahest_address_config_path=_ADDRESSES,
        escrow_proposal=proposal,
        now_unix=_EXPIRATION - 3600,
        get_obligation_fn=_get_obligation,
    )


def test_a_native_entry_names_no_token() -> None:
    proposal = _native_proposal()
    assert "token" not in proposal.fields
    assert "token" not in (proposal.literal_fields or {})


async def test_a_native_escrow_from_the_listing_entry_verifies() -> None:
    assert await _verify(_native_proposal()) == 0


async def test_a_key_the_chain_lacks_is_named_in_the_mismatch() -> None:
    proposal = _native_proposal().model_copy(update={"fields": {"token": None}})
    with pytest.raises(EscrowVerificationError) as exc:
        await _verify(proposal)
    assert "token: chain=<absent> expected=None" in str(exc.value)
