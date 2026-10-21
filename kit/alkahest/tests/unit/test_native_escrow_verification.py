"""A native-token escrow verifies against its decoded obligation.

Runs the proposal a seller derives from its accepted escrow entry through the
listing form of the settlement verifier, and the plan a seller commits when it
accepts that proposal through the plan form, with the chain read replaced by
the SDK's own decoded obligation type, against the development chain's address
book.
"""

from __future__ import annotations

import json
from pathlib import Path
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
    verify_escrow_against_plan,
    verify_escrow_for_settlement,
)
from market_alkahest.plans import materialize_settlement_plan_from_proposal
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


# The listing the native escrow is negotiated against, stated as a seller may
# store it: addresses lowercased.
_LISTING = {
    "demands": [{
        "chain_name": _CHAIN,
        "arbiter": get_recipient_arbiter(_CHAIN, config_path=_ADDRESSES).lower(),
        "demand_data": {"recipient": _SELLER.lower()},
    }],
}


def _native_proposal() -> EscrowProposal:
    entry = {
        "chain_name": _CHAIN,
        "escrow_address": NativeTokenDefaultEscrowCodec().resolve_address(
            _CHAIN, config_path=_ADDRESSES,
        ),
        "literal_fields": {},
        "rates": [{"field": "amount", "per": "hour", "value": str(_AMOUNT)}],
    }
    return escrow_proposal_from_accepted_entry(
        listing=_LISTING, entry=entry, expiration_unix=_EXPIRATION,
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
        listing=_LISTING,
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


# --- Verification against the plan committed at acceptance ------------------


def _plan(proposal: EscrowProposal) -> dict:
    """The plan a seller commits when it accepts ``proposal`` against ``_LISTING``."""
    return materialize_settlement_plan_from_proposal(
        proposal=proposal,
        listing=_LISTING,
        agreed_amount=_AMOUNT,
        duration_seconds=3600,
        addr_config_path=_ADDRESSES,
    ).model_dump(mode="json")


def _chain_client(data, *, expiration: int = _EXPIRATION):
    """An Alkahest client whose native escrow reads answer ``data``, as the SDK's do."""
    attestation = SimpleNamespace(revocation_time=0, expiration_time=expiration)

    async def get_obligation(_uid):
        return {"attestation": attestation, "data": data}

    default = SimpleNamespace(get_obligation=get_obligation)
    return SimpleNamespace(
        native_token=SimpleNamespace(escrow=SimpleNamespace(default=default))
    )


def _funded(recipient: str = _SELLER, amount: int = _AMOUNT):
    return NativeTokenEscrowObligationData(
        _arbiter(), encode_recipient_demand(recipient), str(amount),
    )


async def _verify_plan(plan, client, *, addresses: str = _ADDRESSES) -> int:
    return await verify_escrow_against_plan(
        escrow_uid="0x" + "ab" * 32,
        settlement_plan=plan,
        alkahest_client=client,
        chain_name=_CHAIN,
        escrow_address=_native_proposal().escrow_address,
        alkahest_address_config_path=addresses,
        now_unix=_EXPIRATION - 3600,
    )


# Anvil's deterministic development account #3; never use it on a public network.
_OTHER_WALLET = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"


async def test_an_escrow_funding_the_committed_plan_verifies() -> None:
    assert await _verify_plan(_plan(_native_proposal()), _chain_client(_funded())) == 0


def _book_with_moved_arbiter(tmp_path) -> str:
    """The development address book with its recipient arbiter redeployed."""
    book = json.loads(Path(_ADDRESSES).read_text())
    # A development address standing for a redeployed arbiter.
    book["arbiters_addresses"]["recipient_arbiter"] = "0x" + "ee" * 20
    changed_book = tmp_path / "changed-addresses.json"
    changed_book.write_text(json.dumps(book))
    return str(changed_book)


@pytest.mark.parametrize(
    ("change", "named"),
    [
        # The accepted proposal selected the condition paying the old wallet,
        # which the changed listing no longer authorizes.
        pytest.param("wallet", "release_condition_not_authorized", id="seller wallet"),
        pytest.param("arbiter", "arbiter", id="address book arbiter"),
    ],
)
async def test_a_listing_changed_since_acceptance_does_not_change_what_verifies(
    tmp_path, change, named
) -> None:
    """The committed plan verifies after the seller pays another wallet, or after
    its address book moves the arbiter; the listing form, deriving from the
    listing and address book as they now stand, refuses the same escrow over the
    term that changed."""
    plan = _plan(_native_proposal())
    addresses = _book_with_moved_arbiter(tmp_path) if change == "arbiter" else _ADDRESSES
    recipient = _OTHER_WALLET if change == "wallet" else _SELLER
    changed_listing = {
        "demands": [{
            "chain_name": _CHAIN,
            "arbiter": _arbiter().lower(),
            "demand_data": {"recipient": recipient.lower()},
        }],
    }

    assert (
        await _verify_plan(plan, _chain_client(_funded()), addresses=addresses) == 0
    )
    with pytest.raises(EscrowVerificationError) as refused:
        await verify_escrow_for_settlement(
            escrow_uid="0x" + "ab" * 32,
            seller_wallet=recipient,
            agreed_price=_AMOUNT,
            agreed_duration_seconds=3600,
            listing=changed_listing,
            alkahest_client=_chain_client(_funded()),
            chain_name=_CHAIN,
            alkahest_address_config_path=addresses,
            escrow_proposal=_native_proposal(),
            now_unix=_EXPIRATION - 3600,
        )
    assert named in str(refused.value)


@pytest.mark.parametrize(
    ("recipient", "amount", "expiration", "named"),
    [
        pytest.param(_SELLER, _AMOUNT - 1, _EXPIRATION, "amount", id="amount"),
        pytest.param(_OTHER_WALLET, _AMOUNT, _EXPIRATION, "demand", id="recipient"),
        pytest.param(
            _SELLER, _AMOUNT, _EXPIRATION + 60, "expiration_time", id="expiry"
        ),
    ],
)
async def test_an_escrow_differing_from_the_plan_does_not_verify(
    recipient, amount, expiration, named
) -> None:
    client = _chain_client(_funded(recipient, amount), expiration=expiration)

    with pytest.raises(EscrowVerificationError) as refused:
        await _verify_plan(_plan(_native_proposal()), client)

    assert named in str(refused.value)


async def test_a_plan_with_no_obligation_on_the_escrow_contract_refuses() -> None:
    plan = _plan(_native_proposal())
    plan["obligations"][0]["params"]["escrow_contract"] = "0x" + "12" * 20

    with pytest.raises(EscrowVerificationError, match="holds no obligation"):
        await _verify_plan(plan, _chain_client(_funded()))
