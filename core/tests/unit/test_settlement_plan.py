"""SettlementObligation / SettlementPlan carrier contract.

The plan carrier is mechanism-neutral: lifecycle universals as typed
fields, mechanism specifics behind ``{mechanism, params}``. It is never
parsed from a mechanism's flat shape: a flat ``EscrowTerms`` dict or a bare
list of them is refused, and the mechanism codec converts between the two.
"""

import pytest
from pydantic import ValidationError

from market_core.schemas import (
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

ENVELOPE = {
    "payer": "buyer",
    "claimant": "seller",
    "amount": "2000000",
    "asset": "0x" + "33" * 20,
    "expiration_unix": 4_102_444_800,
    "mechanism": "alkahest.v1",
    "params": {"chain_name": "base_sepolia"},
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


def test_plan_round_trip_preserves_scheme_tagged_parties() -> None:
    buyer = {"scheme": "ed25519", "identifier": "buyer"}
    seller = {"scheme": "ed25519", "identifier": "seller"}
    plan = SettlementPlan(
        buyer_principal=buyer,
        seller_principal=seller,
        obligations=[
            SettlementObligation(
                payer="buyer",
                claimant="seller",
                payer_principal=buyer,
                claimant_principal=seller,
                amount=2000,
                asset="usd",
                expiration_unix=4_102_444_800,
                mechanism="example.payment.v1",
            )
        ],
    )

    again = SettlementPlan.model_validate(plan.model_dump())

    assert again.buyer_principal == buyer
    assert again.seller_principal == seller
    assert again.obligations[0].payer_principal == buyer
    assert again.obligations[0].claimant_principal == seller


def test_mechanism_is_required_on_envelope_shapes():
    with pytest.raises(ValidationError):
        SettlementObligation(
            payer="buyer",
            claimant="seller",
            expiration_unix=4_102_444_800,
            params={},
        )


def test_a_flat_escrow_terms_dict_is_not_an_obligation():
    with pytest.raises(ValidationError):
        SettlementObligation.model_validate(FLAT_PAYMENT_TERMS)


def test_envelope_shape_passes_through_untouched():
    envelope = {
        "payer": "buyer",
        "claimant": "seller",
        "expiration_unix": 4_102_444_800,
        "mechanism": "example.payment.v1",
        "params": {"provider": "example", "currency": "USD"},
    }
    ob = SettlementObligation.model_validate(envelope)
    assert ob.mechanism == "example.payment.v1"
    assert ob.params == {"provider": "example", "currency": "USD"}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param([FLAT_PAYMENT_TERMS], id="a bare terms list"),
        pytest.param([ENVELOPE], id="a bare envelope list"),
        pytest.param({"obligations": [FLAT_PAYMENT_TERMS]}, id="flat terms inside"),
    ],
)
def test_a_plan_is_parsed_only_from_its_own_shape(value):
    with pytest.raises(ValidationError):
        SettlementPlan.model_validate(value)


def test_plan_round_trip_with_service_terms():
    plan = SettlementPlan(
        obligations=[SettlementObligation.model_validate(ENVELOPE)],
        service_terms={"heartbeat": {"interval_seconds": 60}},
    )
    again = SettlementPlan.model_validate(plan.model_dump())
    assert again.service_terms["heartbeat"]["interval_seconds"] == 60
    assert again.obligations[0].amount == 2_000_000
