"""Agreement-to-policy mapping and the single acceptance wire shape."""

from __future__ import annotations

import pytest
from market_core.schemas import Agreement, derive_settlement_option_id

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
    changed_authority = agreement()
    changed_authority["settlement"]["lifecycle"]["adjudication"]["dispute"]["account"] = OTHER
    with pytest.raises(MandatePolicyError):
        stored.require_bound_to(changed_authority)


def test_accepted_data_survives_later_policy_changes():
    """Fees stay bound to acceptance; authority identity is fixed by the option."""
    stored = PaymentSettlementData.for_agreement(agreement(), config(fee_bps=250))
    # New deals can use different fees and authorities, yet an accepted one
    # stays valid against its own option and acceptance-time policy.
    later = PaymentSettlementData.for_agreement(agreement(dispute=OTHER), config(fee_bps=0))
    assert later.transaction_id != stored.transaction_id
    stored.require_bound_to(agreement())


def test_extra_reverse_authorities_are_refused():
    stored = PaymentSettlementData.for_agreement(agreement(), config())
    wire = stored.to_wire()
    wire["mandate"]["parts"][0]["authorities"]["reverse"].append(OTHER)
    from market_arkhai_payments import transaction_id

    tampered = PaymentSettlementData.parse(
        {"mandate": wire["mandate"], "transaction_id": transaction_id(wire["mandate"])}
    )
    with pytest.raises(MandatePolicyError):
        tampered.require_bound_to(agreement())


def test_policy_requires_payments_selection_payer_and_trusted_policy():
    other = agreement()
    other["settlement"]["settlement"]["schema"] = "alkahest.v1"
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(other, config())
    missing_lifecycle = agreement()
    del missing_lifecycle["settlement"]["lifecycle"]
    with pytest.raises(MandatePolicyError, match="lifecycle.adjudication.dispute"):
        mandate_policy_for_agreement(missing_lifecycle, config())
    missing_payer = agreement()
    missing_payer["settlement_params"] = {}
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(missing_payer, config())
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(agreement(), config(fee_bps=None))
    with pytest.raises(MandatePolicyError):
        mandate_policy_for_agreement(agreement(), config(), expected_payer=OTHER)


@pytest.mark.parametrize("duration_seconds", [3600, 7200, 172_800])
def test_the_mandate_charges_the_accepted_total_once_whatever_the_duration(duration_seconds):
    accepted = agreement(duration_seconds=duration_seconds, amount="10000")
    data = PaymentSettlementData.for_agreement(accepted, config())
    (part,) = data.to_wire()["mandate"]["parts"]
    assert int(part["amount"]) == 10000
    data.require_bound_to(accepted)


def _per_period(accepted: dict) -> dict:
    """``accepted`` with its option billed per PT15M period, under the option's new ID."""
    option = dict(accepted["settlement"])
    option.pop("option_id")
    option["settlement"] = {**option["settlement"], "period": "PT15M"}
    option["option_id"] = derive_settlement_option_id(**option)
    return {**accepted, "settlement": option}


def test_a_payments_option_billed_per_period_gets_no_once_mandate():
    # The installed adapter services once parts only. Its projection refuses an
    # option carrying a period, so an Agreement whose amount is one period's
    # price never becomes a once mandate charging that price for the horizon.
    recurring = _per_period(agreement(duration_seconds=172_800, amount="625000"))
    Agreement.model_validate(recurring)
    with pytest.raises(MandatePolicyError, match="lacks the terms a payments mandate needs"):
        mandate_policy_for_agreement(recurring, config())
    with pytest.raises(MandatePolicyError, match="lacks the terms a payments mandate needs"):
        PaymentSettlementData.for_agreement(recurring, config())
    stored = PaymentSettlementData.for_agreement(agreement(duration_seconds=172_800, amount="625000"), config())
    with pytest.raises(MandatePolicyError, match="stored payment mandate is malformed"):
        stored.require_bound_to(recurring)


def test_agreement_bytes_must_hold_a_json_object():
    assert agreement_from_bytes(agreement_bytes(agreement()))["negotiation_id"] == "neg-1"
    with pytest.raises(MandatePolicyError):
        agreement_from_bytes(b"[]")
    with pytest.raises(MandatePolicyError):
        agreement_from_bytes(b"not json")
