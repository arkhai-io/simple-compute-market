"""A seller plan for a selected Alkahest option funds the escrow it names."""

from __future__ import annotations

import pytest

from market_alkahest.plans import SettlementPlan, escrow_terms_to_settlement_obligation
from market_alkahest.proposals import validate_selected_escrow_plan
from market_alkahest.schemas import EscrowTerms

_ESCROW = "0x" + "11" * 20
_TOKEN = "0x" + "aa" * 20
_ARBITER = "0x" + "22" * 20

_ENTRY = {
    "chain_name": "anvil",
    "escrow_address": _ESCROW,
    "literal_fields": {"token": _TOKEN},
    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
}
_LISTING = {
    "accepted_escrows": [_ENTRY],
    "demands": [{"chain_name": "anvil", "arbiter": _ARBITER, "demand_data": {}}],
}


def _plan(**overrides) -> SettlementPlan:
    data = {
        "maker": "buyer",
        "chain_name": "anvil",
        "escrow_contract": _ESCROW.upper().replace("0X", "0x"),
        "obligation_data": {
            "arbiter": _ARBITER,
            "demand": "0x" + "cd" * 32,
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
    validate_selected_escrow_plan(_plan(), listing=_LISTING, entry=_ENTRY)
    # Any model of the shared plan contract is read through its wire form.
    validate_selected_escrow_plan(
        _plan().model_dump(mode="json"), listing=_LISTING, entry=_ENTRY
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"chain_name": "base_sepolia"}, "another chain"),
        ({"escrow_contract": "0x" + "33" * 20}, "another escrow contract"),
        ({"obligation_data": {"token": "0x" + "44" * 20}}, "another token"),
        ({"obligation_data": {"arbiter": "0x" + "55" * 20}}, "another arbiter"),
    ],
)
def test_a_plan_for_another_escrow_is_refused(overrides, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_selected_escrow_plan(_plan(**overrides), listing=_LISTING, entry=_ENTRY)


def test_a_plan_of_several_obligations_is_refused() -> None:
    plan = _plan()
    doubled = plan.model_copy(update={"obligations": plan.obligations * 2})

    with pytest.raises(ValueError, match="single escrow obligation"):
        validate_selected_escrow_plan(doubled, listing=_LISTING, entry=_ENTRY)
