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
from market_arkhai_payments.fixtures import FakePaymentsClient

from payment_terms import (
    BUYER,
    IMPOSTOR,
    OTHER,
    SERVICE,
    agreement,
    agreement_bytes,
    config,
    option,
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


def test_another_payer_or_advertised_option_is_refused():
    terms = agreement(payer=OTHER)
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient()).check(agreement_bytes(terms), _seller_data(terms))
    terms = agreement()
    with pytest.raises(MandatePolicyError):
        _approval(FakePaymentsClient()).check(
            agreement_bytes(terms), _seller_data(terms), advertised_option=option(deposit=True)
        )


def test_a_declined_confirmation_approves_nothing():
    fake = FakePaymentsClient(signer=SERVICE)
    terms = agreement()
    with pytest.raises(PaymentApprovalDeclined):
        _approval(fake).approve(
            agreement_bytes(terms), _seller_data(terms), confirm=lambda *_: False
        )
    assert fake.count("approve") == 0


def test_an_approval_receipt_from_another_key_is_refused():
    fake = FakePaymentsClient(signer=IMPOSTOR)
    terms = agreement()
    with pytest.raises(ReceiptVerificationError):
        _approval(fake).approve(agreement_bytes(terms), _seller_data(terms))
