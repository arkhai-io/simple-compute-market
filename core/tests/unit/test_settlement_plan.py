"""SettlementObligation / SettlementPlan carrier contract.

The plan carrier is mechanism-neutral: lifecycle universals as typed
fields, mechanism specifics behind ``{mechanism, params}``. The legacy
coercions must keep pre-plan artifacts — flat ``EscrowTerms`` dicts and
bare terms lists from old run logs / negotiation threads — parsing.
"""

import pytest
from pydantic import ValidationError

from market_core.schemas import (
    EscrowTerms,
    SettlementObligation,
    SettlementPlan,
)

FLAT_PAYMENT_TERMS = {
    "maker": "buyer",
    "chain_name": "base_sepolia",
    "escrow_contract": "0x" + "11" * 20,
    "obligation_data": {
        "arbiter": "0x" + "22" * 20,
        "demand": "0x" + "ab" * 32,
        "token": "0x" + "33" * 20,
        "amount": 2_000_000,
    },
    "expiration_unix": 4_102_444_800,
}


def test_envelope_round_trip_serializes_amount_as_string():
    ob = SettlementObligation(
        payer="buyer",
        claimant="seller",
        amount=2 * 10**18,
        asset="0x" + "33" * 20,
        expiration_unix=4_102_444_800,
        mechanism="alkahest.v1",
        params={"chain_name": "base_sepolia"},
    )
    dumped = ob.model_dump()
    assert dumped["amount"] == str(2 * 10**18)
    again = SettlementObligation.model_validate(dumped)
    assert again.amount == 2 * 10**18
    assert again.mechanism == "alkahest.v1"


def test_mechanism_is_required_on_envelope_shapes():
    with pytest.raises(ValidationError):
        SettlementObligation(
            payer="buyer",
            claimant="seller",
            expiration_unix=4_102_444_800,
            params={},
        )


def test_legacy_flat_escrow_terms_coerce_into_envelope():
    ob = SettlementObligation.model_validate(FLAT_PAYMENT_TERMS)
    assert ob.payer == "buyer"
    assert ob.claimant == "seller"
    assert ob.mechanism == "alkahest.v1"
    assert ob.amount == 2_000_000
    assert ob.asset == FLAT_PAYMENT_TERMS["obligation_data"]["token"]
    assert ob.expiration_unix == FLAT_PAYMENT_TERMS["expiration_unix"]
    assert ob.params["chain_name"] == "base_sepolia"
    assert ob.params["escrow_contract"] == FLAT_PAYMENT_TERMS["escrow_contract"]
    assert ob.params["obligation_data"] == FLAT_PAYMENT_TERMS["obligation_data"]
    assert ob.conditions == []


def test_legacy_seller_maker_coerces_to_buyer_claimant():
    bond = dict(FLAT_PAYMENT_TERMS, maker="seller")
    ob = SettlementObligation.model_validate(bond)
    assert ob.payer == "seller"
    assert ob.claimant == "buyer"


def test_legacy_terms_model_dump_coerces_identically():
    terms = EscrowTerms.model_validate(FLAT_PAYMENT_TERMS)
    ob = SettlementObligation.model_validate(terms.model_dump())
    assert ob.params["obligation_data"] == terms.obligation_data
    assert ob.expiration_unix == terms.expiration_unix


def test_legacy_non_scalar_obligation_has_no_amount_or_asset():
    bundle = dict(
        FLAT_PAYMENT_TERMS,
        obligation_data={
            "arbiter": "0x" + "22" * 20,
            "demand": "0x" + "ab" * 32,
            "erc20Tokens": ["0x" + "33" * 20],
            "erc20Amounts": [5],
        },
    )
    ob = SettlementObligation.model_validate(bundle)
    assert ob.amount is None
    assert ob.asset is None
    assert ob.params["obligation_data"]["erc20Amounts"] == [5]


def test_legacy_terms_without_chain_name_omit_it_from_params():
    flat = dict(FLAT_PAYMENT_TERMS)
    flat.pop("chain_name")
    ob = SettlementObligation.model_validate(flat)
    assert "chain_name" not in ob.params


def test_envelope_shape_passes_through_untouched():
    envelope = {
        "payer": "buyer",
        "claimant": "seller",
        "expiration_unix": 4_102_444_800,
        "mechanism": "fiat.stripe.v1",
        "params": {"provider": "stripe", "currency": "USD"},
    }
    ob = SettlementObligation.model_validate(envelope)
    assert ob.mechanism == "fiat.stripe.v1"
    assert ob.params == {"provider": "stripe", "currency": "USD"}


def test_plan_coerces_bare_legacy_terms_list():
    plan = SettlementPlan.model_validate([FLAT_PAYMENT_TERMS])
    assert len(plan.obligations) == 1
    assert plan.obligations[0].mechanism == "alkahest.v1"
    assert plan.service_terms == {}


def test_plan_round_trip_with_service_terms():
    plan = SettlementPlan(
        obligations=[SettlementObligation.model_validate(FLAT_PAYMENT_TERMS)],
        service_terms={"heartbeat": {"interval_seconds": 60}},
    )
    again = SettlementPlan.model_validate(plan.model_dump())
    assert again.service_terms["heartbeat"]["interval_seconds"] == 60
    assert again.obligations[0].amount == 2_000_000


def test_plan_accepts_mixed_legacy_and_envelope_entries():
    envelope = {
        "payer": "seller",
        "claimant": "buyer",
        "expiration_unix": 4_102_444_800,
        "mechanism": "alkahest.v1",
        "params": {},
    }
    plan = SettlementPlan.model_validate([FLAT_PAYMENT_TERMS, envelope])
    assert [ob.payer for ob in plan.obligations] == ["buyer", "seller"]
