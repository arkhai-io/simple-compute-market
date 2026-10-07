"""Seller receipt outcomes, deposit ordering, and reversal classification."""

from __future__ import annotations

import pytest

from market_arkhai_payments import (
    ArkhaiPaymentsConfigurationError,
    NotPaid,
    NothingToReverse,
    PaymentSellerStage,
    PaymentSettlementData,
    PaymentsUnavailable,
    ReceiptInvalid,
    ReceiptPending,
    ReceiptUnavailable,
    ReceiptVerified,
    RefundUnavailable,
    Refunded,
)
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt

from payment_terms import IMPOSTOR, PAYEE, SERVICE, agreement, config


def _stage(fake, **overrides):
    return PaymentSellerStage(config(**overrides), client_for_owner=fake)


def _accepted(**terms):
    value = agreement(**terms)
    return value, PaymentSettlementData.for_agreement(value, config())


def test_stage_requires_complete_trusted_policy():
    for missing in ("fee_bps", "dispute_authority", "service_identity"):
        with pytest.raises(ArkhaiPaymentsConfigurationError):
            PaymentSellerStage(config(**{missing: None}))


def test_no_transaction_yet_is_pending_and_reads_once_as_the_payee():
    fake = FakePaymentsClient()
    terms, data = _accepted()
    assert _stage(fake).check_receipt_now(terms, data) == ReceiptPending(data.transaction_id)
    assert fake.count("get_transaction") == 1
    assert fake.owners == [PAYEE]


def test_a_service_receipt_verifies():
    fake = FakePaymentsClient()
    terms, data = _accepted()
    fake.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    outcome = _stage(fake).check_receipt_now(terms, data)
    assert isinstance(outcome, ReceiptVerified)


def test_impostor_and_wrong_mandate_receipts_are_invalid():
    terms, data = _accepted()
    impostor = FakePaymentsClient()
    impostor.serve(build_signed_receipt(signer=IMPOSTOR, mandate=data.mandate))
    assert isinstance(_stage(impostor).check_receipt_now(terms, data), ReceiptInvalid)
    other = PaymentSettlementData.for_agreement(agreement(amount="99"), config())
    wrong = FakePaymentsClient()
    wrong.serve(build_signed_receipt(signer=SERVICE, mandate=other.mandate))
    assert isinstance(_stage(wrong).check_receipt_now(terms, data), ReceiptInvalid)


def test_transport_failure_and_unexpected_codes_are_unavailable():
    terms, data = _accepted()
    down = FakePaymentsClient()
    down.unavailable = True
    assert isinstance(_stage(down).check_receipt_now(terms, data), ReceiptUnavailable)

    def missing_credential(_owner):
        raise ArkhaiPaymentsConfigurationError("credential unavailable")

    stage = PaymentSellerStage(config(), client_for_owner=missing_credential)
    assert isinstance(stage.check_receipt_now(terms, data), ReceiptUnavailable)


def test_deposit_runs_only_when_advertised_and_is_idempotent():
    fake = FakePaymentsClient()
    terms, data = _accepted()
    _stage(fake).deposit_now(terms, data)
    assert fake.count("ensure_agreement_attached") == 0

    terms, data = _accepted(deposit=True)
    fake.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    _stage(fake).deposit_now(terms, data)
    _stage(fake).deposit_now(terms, data)
    assert len(fake.attachments) == 1


def test_a_failed_deposit_is_unavailable():
    fake = FakePaymentsClient()
    fake.attach_unavailable = True
    terms, data = _accepted(deposit=True)
    with pytest.raises(PaymentsUnavailable):
        _stage(fake).deposit_now(terms, data)


def test_reversal_requires_a_verified_payment_first():
    terms, data = _accepted()
    unpaid = FakePaymentsClient()
    assert isinstance(_stage(unpaid).reverse_now(terms, data), NotPaid)
    assert unpaid.count("reverse") == 0

    impostor = FakePaymentsClient()
    impostor.serve(build_signed_receipt(signer=IMPOSTOR, mandate=data.mandate))
    assert isinstance(_stage(impostor).reverse_now(terms, data), NotPaid)
    assert impostor.count("reverse") == 0


def test_reversal_outcomes_follow_service_codes():
    terms, data = _accepted()
    receipt = build_signed_receipt(signer=SERVICE, mandate=data.mandate)

    paid = FakePaymentsClient()
    paid.serve(receipt)
    assert isinstance(_stage(paid).reverse_now(terms, data), Refunded)

    for code in ("hold_matured", "hold_not_reversible", "insufficient_held_funds"):
        matured = FakePaymentsClient()
        matured.serve(receipt)
        matured.reverse_error = code
        assert isinstance(_stage(matured).reverse_now(terms, data), NothingToReverse)

    failing = FakePaymentsClient()
    failing.serve(receipt)
    failing.reverse_error = "ledger_unavailable"
    assert isinstance(_stage(failing).reverse_now(terms, data), RefundUnavailable)


def test_accepted_state_must_derive_its_stored_settlement_data():
    from market_arkhai_payments import MandatePolicyError

    from payment_terms import agreement_bytes

    terms, data = _accepted()
    stage = _stage(FakePaymentsClient())
    decoded, parsed = stage.accepted(agreement_bytes(terms), data.to_wire())
    assert decoded == terms and parsed == data
    with pytest.raises(MandatePolicyError):
        stage.accepted(agreement_bytes(agreement(amount="20000")), data.to_wire())
