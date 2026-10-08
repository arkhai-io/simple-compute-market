"""Seller receipt outcomes, deposit ordering, and reversal classification."""

from __future__ import annotations

import pytest

from market_arkhai_payments import (
    ArkhaiPaymentsConfigurationError,
    MandatePolicyError,
    PaymentsBlocked,
    ReceiptBlocked,
    RefundBlocked,
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


def test_stage_needs_only_servicing_configuration():
    for missing in ("service_url", "service_identity"):
        with pytest.raises(ArkhaiPaymentsConfigurationError):
            PaymentSellerStage(config(**{missing: None}))
    stage = PaymentSellerStage(config(fee_bps=None, dispute_authority=None))
    with pytest.raises(MandatePolicyError):
        stage.settlement_data(agreement())


def test_a_disabled_mechanism_still_services_accepted_deals():
    fake = FakePaymentsClient()
    terms, data = _accepted()
    fake.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    stage = PaymentSellerStage(config(enabled=False), client_for_owner=fake)
    assert isinstance(stage.check_receipt_now(terms, data), ReceiptVerified)


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


@pytest.mark.parametrize(
    "status,code",
    [(503, "ledger_unavailable"), (503, "account_directory_unavailable"),
     (500, "internal_error"), (429, "rate_limited"), (502, "bad_gateway")],
)
def test_transient_failures_are_unavailable(status, code):
    terms, data = _accepted()
    fake = FakePaymentsClient()
    fake.read_error = (status, code)
    assert isinstance(_stage(fake).check_receipt_now(terms, data), ReceiptUnavailable)
    down = FakePaymentsClient()
    down.unavailable = True
    assert isinstance(_stage(down).check_receipt_now(terms, data), ReceiptUnavailable)


@pytest.mark.parametrize(
    "status,code",
    [(401, "authentication_required"), (403, "caller_not_authorized"), (404, "account_not_found")],
)
def test_operator_failures_are_blocked(status, code):
    terms, data = _accepted()
    fake = FakePaymentsClient()
    fake.read_error = (status, code)
    assert isinstance(_stage(fake).check_receipt_now(terms, data), ReceiptBlocked)


def test_missing_credentials_and_contract_violations_are_blocked():
    terms, data = _accepted()

    def missing_credential(_owner):
        raise ArkhaiPaymentsConfigurationError("credential unavailable")

    stage = PaymentSellerStage(config(), client_for_owner=missing_credential)
    assert isinstance(stage.check_receipt_now(terms, data), ReceiptBlocked)

    class OtherTransaction(FakePaymentsClient):
        def get_transaction(self, transaction):
            return super().get_transaction("0" * 64)

    other = OtherTransaction()
    other.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    assert isinstance(_stage(other).check_receipt_now(terms, data), ReceiptBlocked)


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


def test_a_failed_deposit_is_unavailable_or_blocked():
    fake = FakePaymentsClient()
    fake.attach_unavailable = True
    terms, data = _accepted(deposit=True)
    with pytest.raises(PaymentsUnavailable):
        _stage(fake).deposit_now(terms, data)

    stray = FakePaymentsClient()
    stray.attachments.append({"sha256": "f" * 64})
    with pytest.raises(PaymentsBlocked):
        _stage(stray).deposit_now(terms, data)


def test_a_repeated_reversal_completes_after_an_earlier_one():
    terms, data = _accepted()
    fake = FakePaymentsClient()
    fake.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    fake.reversed = True
    fake.reverse_error = "hold_not_reversible"
    outcome = _stage(fake).reverse_now(terms, data)
    assert isinstance(outcome, Refunded) and outcome.event is None


def test_reversal_operator_failures_are_blocked():
    terms, data = _accepted()
    fake = FakePaymentsClient()
    fake.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    fake.reverse_error = "caller_not_authorized"
    assert isinstance(_stage(fake).reverse_now(terms, data), RefundBlocked)


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


def test_accepted_state_must_bind_its_stored_settlement_data():
    from payment_terms import agreement_bytes

    terms, data = _accepted()
    stage = _stage(FakePaymentsClient())
    decoded, parsed = stage.accepted(agreement_bytes(terms), data.to_wire())
    assert decoded == terms and parsed == data
    with pytest.raises(MandatePolicyError):
        stage.accepted(agreement_bytes(agreement(amount="20000")), data.to_wire())


def test_servicing_stage_follows_servicing_fields_not_enabled():
    from market_arkhai_payments import servicing_stage

    assert servicing_stage(None) is None
    assert servicing_stage(config(enabled=False)) is not None
    assert servicing_stage(config(enabled=False, service_identity=None)) is None
