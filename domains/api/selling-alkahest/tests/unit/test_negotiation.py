"""The escrow's negotiation parts: the opening's proposal step and the accepted artifacts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.proposals import ReleaseConditionError
from market_negotiation_runtime import OfferUnfulfillableError

from arkhai_api_selling_alkahest.negotiation import (
    AlkahestEscrowAcceptance,
    accepted_escrow_artifacts,
    accepted_escrow_proposal,
)
from tests.bundles import BUYER, SELLER

# Placeholder development addresses, never used on a public network.
TOKEN = "0x" + "01" * 20
ESCROW = "0x" + "11" * 20
SELLER_WALLET = "0x" + "33" * 20
PATHS = {"anvil": str(anvil_address_book_path())}
CONDITION = {
    "chain_name": "anvil",
    "arbiter": get_recipient_arbiter("anvil", config_path=PATHS["anvil"]),
    "demand_data": {"recipient": SELLER_WALLET},
}
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil", "escrow_address": ESCROW, "literal_fields": {"token": TOKEN},
    "rates": [{"field": "amount", "per": "token", "value": "100"}],
}]


def _proposal(**overrides):
    return {
        "chain_name": "anvil", "escrow_address": ESCROW, "fields": {"token": TOKEN, "amount": 300},
        "literal_fields": {"token": TOKEN}, "rates": [{"field": "amount", "per": "token", "value": "100"}],
        "demand": CONDITION, "expiration_unix": 1_800_000_000, **overrides,
    }


def test_the_opening_proposal_is_canonicalized_against_the_listings_escrows():
    canonical = accepted_escrow_proposal(_proposal(), ACCEPTED_ESCROWS)

    assert canonical["escrow_address"] == ESCROW
    assert canonical["fields"]["token"] == TOKEN


def test_the_accepted_artifacts_settle_under_the_listings_condition_between_the_parties():
    artifacts = accepted_escrow_artifacts(
        buyer_principal=BUYER, seller_principal=SELLER.identity, proposal=_proposal(),
        listing={"accepted_escrows": ACCEPTED_ESCROWS, "demands": [CONDITION]},
        agreed_amount=300, chain_config_paths=PATHS,
    )

    plan = artifacts["settlement_plan"]
    assert plan["buyer_principal"] == BUYER.model_dump(mode="json")
    assert plan["seller_principal"] == SELLER.identity.model_dump(mode="json")
    assert all(
        obligation["payer_principal"] == BUYER.model_dump(mode="json")
        and obligation["claimant_principal"] == SELLER.identity.model_dump(mode="json")
        for obligation in plan["obligations"]
    )
    assert artifacts["settlement_selection"]["mechanism"] == ALKAHEST_MECHANISM_ID
    assert artifacts["_agreement_settlement_option"]["asset"] == TOKEN


def test_the_accepted_artifacts_refuse_a_listing_authorizing_no_condition():
    with pytest.raises(ReleaseConditionError, match="release_condition_not_advertised"):
        accepted_escrow_artifacts(
            buyer_principal=BUYER, seller_principal=SELLER.identity, proposal=_proposal(),
            listing={"accepted_escrows": ACCEPTED_ESCROWS, "demands": []},
            agreed_amount=300, chain_config_paths=PATHS,
        )


def test_an_acceptance_the_kit_refuses_is_unfulfillable_before_anything_is_recorded():
    acceptance = SimpleNamespace(
        buyer_principal=BUYER, seller_principal=SELLER.identity, pinned_proposal=_proposal(),
        agreed_amount=300, uses_scalar_amount=True,
        listing_record={"accepted_escrows": ACCEPTED_ESCROWS, "demands": []},
    )
    escrow = AlkahestEscrowAcceptance(lambda: PATHS)

    with pytest.raises(OfferUnfulfillableError):
        escrow.accept(acceptance)
    with pytest.raises(OfferUnfulfillableError):
        escrow.offer(acceptance)
