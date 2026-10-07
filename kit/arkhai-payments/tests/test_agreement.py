"""Agreement-to-policy mapping and the single acceptance wire shape."""

from __future__ import annotations

import pytest

from market_arkhai_payments import (
    MandatePolicyError,
    PaymentSettlementData,
    agreement_from_bytes,
    mandate_policy_for_agreement,
    transaction_id,
)

from payment_terms import OTHER, agreement, agreement_bytes, config


def test_settlement_data_round_trips_through_its_wire_shape():
    data = PaymentSettlementData.for_agreement(agreement(), config())
    wire = data.to_wire()
    assert set(wire) == {"mandate", "transaction_id"}
    assert wire["transaction_id"] == transaction_id(data.mandate)
    assert PaymentSettlementData.parse(wire) == data


def test_a_transaction_id_for_another_mandate_is_refused():
    wire = PaymentSettlementData.for_agreement(agreement(), config()).to_wire()
    wire["transaction_id"] = "0" * 64
    with pytest.raises(MandatePolicyError):
        PaymentSettlementData.parse(wire)


def test_the_bare_mandate_shape_is_refused():
    wire = PaymentSettlementData.for_agreement(agreement(), config()).to_wire()
    with pytest.raises(MandatePolicyError):
        PaymentSettlementData.parse(wire["mandate"])


def test_stored_data_must_be_derived_from_the_exact_agreement():
    stored = PaymentSettlementData.for_agreement(agreement(), config())
    stored.require_derived_from(agreement(), config())
    with pytest.raises(MandatePolicyError):
        stored.require_derived_from(agreement(amount="20000"), config())


def test_policy_requires_payments_selection_payer_and_trusted_policy():
    other = agreement()
    other["settlement"] = dict(other["settlement"], mechanism="alkahest.v1")
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(other, config())
    missing_payer = agreement()
    missing_payer["settlement_params"] = {}
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(missing_payer, config())
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(agreement(), config(fee_bps=None))
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(agreement(), config(), expected_payer=OTHER)


def test_agreement_bytes_must_hold_a_json_object():
    assert agreement_from_bytes(agreement_bytes(agreement()))["negotiation_id"] == "neg-1"
    with pytest.raises(MandatePolicyError):
        agreement_from_bytes(b"[]")
    with pytest.raises(MandatePolicyError):
        agreement_from_bytes(b"not json")
