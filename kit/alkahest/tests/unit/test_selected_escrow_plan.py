"""A seller plan for a selected Alkahest option funds the escrow it names."""

from __future__ import annotations

import pytest

from market_alkahest.alkahest import encode_recipient_demand, get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_alkahest.plans import SettlementPlan, escrow_terms_to_settlement_obligation
from market_alkahest.proposals import validate_selected_escrow_plan
from market_alkahest.schemas import EscrowTerms

_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "aa" * 20
_BOOK = str(anvil_address_book_path())
_ARBITER = get_recipient_arbiter("anvil", config_path=_BOOK)
_SELLER = "0x" + "bb" * 20
_DEMAND = "0x" + encode_recipient_demand(_SELLER).hex()

_ENTRY = {
    "chain_name": "anvil",
    "escrow_address": _ESCROW,
    "literal_fields": {"token": _TOKEN},
    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
}
_LISTING = {
    "accepted_escrows": [_ENTRY],
    "demands": [
        {"chain_name": "anvil", "arbiter": _ARBITER, "demand_data": {"recipient": _SELLER}}
    ],
}


def _plan(**overrides) -> SettlementPlan:
    data = {
        "maker": "buyer",
        "chain_name": "anvil",
        "escrow_contract": _ESCROW.upper().replace("0X", "0x"),
        "obligation_data": {
            "arbiter": _ARBITER,
            "demand": _DEMAND,
            "token": _TOKEN,
            "amount": 100,
        },
        "expiration_unix": 1_900_000_000,
    }
    obligation_data = {**data["obligation_data"], **overrides.pop("obligation_data", {})}
    data.update(overrides, obligation_data=obligation_data)
    return SettlementPlan(
        obligations=[escrow_terms_to_settlement_obligation(EscrowTerms(**data))]
    )


def test_the_plan_of_the_selected_escrow_is_accepted() -> None:
    validate_selected_escrow_plan(
        _plan(), listing=_LISTING, entry=_ENTRY, addr_config_path=_BOOK
    )
    # Any model of the shared plan contract is read through its wire form.
    validate_selected_escrow_plan(
        _plan().model_dump(mode="json"),
        listing=_LISTING,
        entry=_ENTRY,
        addr_config_path=_BOOK,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"chain_name": "base_sepolia"}, "another chain"),
        ({"escrow_contract": "0x" + "33" * 20}, "another escrow contract"),
        ({"obligation_data": {"token": "0x" + "44" * 20}}, "another token"),
        ({"obligation_data": {"arbiter": "0x" + "55" * 20}}, "another arbiter"),
        (
            {"obligation_data": {"demand": "0x" + encode_recipient_demand("0x" + "77" * 20).hex()}},
            "another demand",
        ),
    ],
)
def test_a_plan_for_another_escrow_is_refused(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_selected_escrow_plan(
            _plan(**overrides), listing=_LISTING, entry=_ENTRY, addr_config_path=_BOOK
        )


@pytest.mark.parametrize(
    "listing",
    [
        {"accepted_escrows": [_ENTRY]},
        {**_LISTING, "demands": [{**_LISTING["demands"][0], "chain_name": "base_sepolia"}]},
        {**_LISTING, "demands": [{"chain_name": "anvil", "demand_data": {}}]},
    ],
    ids=["no condition", "another chain's condition", "unreadable condition"],
)
def test_a_plan_is_refused_without_a_condition_the_listing_authorizes(listing) -> None:
    with pytest.raises(ValueError, match="release_condition"):
        validate_selected_escrow_plan(
            _plan(), listing=listing, entry=_ENTRY, addr_config_path=_BOOK
        )


def test_a_plan_of_several_obligations_is_refused() -> None:
    plan = _plan()
    doubled = plan.model_copy(update={"obligations": plan.obligations * 2})

    with pytest.raises(ValueError, match="single escrow obligation"):
        validate_selected_escrow_plan(
            doubled, listing=_LISTING, entry=_ENTRY, addr_config_path=_BOOK
        )
