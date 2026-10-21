"""Buyer approval checks and its own attachment policy."""

from __future__ import annotations

import pytest

from market_arkhai_payments import (
    MandatePolicyError,
    PaymentApproval,
    PaymentApprovalDeclined,
    PaymentSettlementData,
    ReceiptVerificationError,
    derive_mandate,
    mandate_policy_for_agreement,
    transaction_id,
)
from market_arkhai_payments.fixtures import FakePaymentsClient, build_signed_receipt

from payment_terms import (
    BUYER,
    IMPOSTOR,
    OTHER,
    SERVICE,
    agreement,
    agreement_bytes,
    config,
)


def _seller_data(terms):
    return PaymentSettlementData.for_agreement(terms, config()).to_wire()


def _approval(fake, **overrides):
    return PaymentApproval(config(**overrides), BUYER, client_for_owner=fake)


def test_approval_returns_the_transaction_and_never_runs_the_seller_deposit():
    fake = FakePaymentsClient(signer=SERVICE)
    terms = agreement(deposit=True)
    txid = _approval(fake).approve(agreement_bytes(terms), _seller_data(terms))
    assert txid == _seller_data(terms)["transaction_id"]
    assert fake.owners == [BUYER]
    assert fake.count("ensure_agreement_attached") == 0
    assert fake.count("attach_agreement") == 0


@pytest.mark.parametrize("attach", [False, True])
@pytest.mark.parametrize("deposit", [False, True])
def test_attachment_follows_only_the_buyer_policy(attach, deposit):
    fake = FakePaymentsClient(signer=SERVICE)
    terms = agreement(deposit=deposit)
    _approval(fake, attach_agreement=attach).approve(agreement_bytes(terms), _seller_data(terms))
    assert fake.calls[0] == ("approve", attach)


def test_a_seller_transaction_id_for_another_mandate_is_refused():
    terms = agreement()
    data = _seller_data(terms)
    data["transaction_id"] = "0" * 64
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient(signer=SERVICE)).check(agreement_bytes(terms), data)


def test_a_mandate_the_buyer_policy_does_not_derive_is_refused():
    terms = agreement()
    lower_fee = derive_mandate(terms, mandate_policy_for_agreement(terms, config(fee_bps=0)))
    data = {
        "mandate": lower_fee.model_dump(mode="json", by_alias=True, exclude_none=True),
        "transaction_id": transaction_id(lower_fee),
    }
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient(signer=SERVICE)).check(agreement_bytes(terms), data)


def test_another_payer_is_refused():
    terms = agreement(payer=OTHER)
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient()).check(agreement_bytes(terms), _seller_data(terms))


def test_a_declined_confirmation_approves_nothing():
    fake = FakePaymentsClient(signer=SERVICE)
    terms = agreement()
    with pytest.raises(PaymentApprovalDeclined):
        _approval(fake).approve(
            agreement_bytes(terms), _seller_data(terms), confirm=lambda *_: False
        )
    assert fake.count("approve") == 0


@pytest.mark.parametrize(
    "configured,signed,verifies",
    [(True, True, True), (True, False, False), (None, True, False)],
    ids=["live-accepts-live", "live-refuses-test", "default-refuses-live"],
)
def test_an_approval_receipt_verifies_only_in_the_configured_mode(configured, signed, verifies):
    fake = FakePaymentsClient(signer=SERVICE, livemode=signed)
    terms = agreement()
    approval = _approval(fake) if configured is None else _approval(fake, livemode=configured)
    if verifies:
        txid = approval.approve(agreement_bytes(terms), _seller_data(terms))
        assert txid == _seller_data(terms)["transaction_id"]
    else:
        with pytest.raises(ReceiptVerificationError):
            approval.approve(agreement_bytes(terms), _seller_data(terms))


def test_a_polled_receipt_is_verified_apart_from_the_approval_receipt():
    class PolledInTestMode(FakePaymentsClient):
        """Approves with a live receipt, then serves a test-mode one when polled."""

        def approve(self, mandate, **kwargs):
            self.approved_mandate = mandate
            return super().approve(mandate, **kwargs)

        def poll(self, transaction, **kwargs):
            self.serve(
                build_signed_receipt(
                    signer=SERVICE, mandate=self.approved_mandate, livemode=False
                )
            )
            return super().poll(transaction, **kwargs)

    fake = PolledInTestMode(signer=SERVICE, livemode=True)
    terms = agreement()
    with pytest.raises(ReceiptVerificationError, match="transaction receipt"):
        _approval(fake, livemode=True).approve(agreement_bytes(terms), _seller_data(terms))
    assert fake.count("approve") == 1


def test_an_approval_receipt_from_another_key_is_refused():
    fake = FakePaymentsClient(signer=IMPOSTOR)
    terms = agreement()
    with pytest.raises(ReceiptVerificationError):
        _approval(fake).approve(agreement_bytes(terms), _seller_data(terms))
