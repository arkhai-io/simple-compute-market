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


def test_stored_data_is_bound_to_the_exact_agreement():
    stored = PaymentSettlementData.for_agreement(agreement(), config())
    stored.require_bound_to(agreement())
    with pytest.raises(MandatePolicyError):
        stored.require_bound_to(agreement(amount="20000"))
    with pytest.raises(MandatePolicyError):
        stored.require_bound_to(agreement(payer=OTHER))


def test_accepted_data_survives_later_policy_changes():
    """Fee and dispute authority are read from the accepted mandate, not current config."""
    stored = PaymentSettlementData.for_agreement(agreement(), config(fee_bps=250))
    # A later configuration with another fee and dispute authority derives a
    # different mandate for new deals, yet the accepted one stays valid.
    later = PaymentSettlementData.for_agreement(
        agreement(), config(fee_bps=0, dispute_authority=OTHER)
    )
    assert later.transaction_id != stored.transaction_id
    stored.require_bound_to(agreement())


def test_extra_reverse_authorities_are_refused():
    stored = PaymentSettlementData.for_agreement(agreement(), config())
    wire = stored.to_wire()
    wire["mandate"]["authorities"]["reverse"].append(OTHER)
    from market_arkhai_payments import transaction_id

    tampered = PaymentSettlementData.parse(
        {"mandate": wire["mandate"], "transaction_id": transaction_id(wire["mandate"])}
    )
    with pytest.raises(MandatePolicyError):
        tampered.require_bound_to(agreement())


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
