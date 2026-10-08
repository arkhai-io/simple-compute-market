"""Receipt verification binds the service signature to the exact Agreement and mandate."""

from __future__ import annotations

from market_arkhai_payments import PaymentSettlementData, verify_receipt
from market_arkhai_payments.fixtures import build_signed_receipt, sign_receipt

from payment_terms import IMPOSTOR, OTHER, SERVICE, agreement, config


def _setup():
    terms = agreement()
    data = PaymentSettlementData.for_agreement(terms, config())
    return terms, data


def _verify(receipt, terms, data):
    return verify_receipt(receipt, SERVICE.identity, mandate=data.mandate, agreement_json=terms)


def test_a_service_receipt_for_the_mandate_verifies():
    terms, data = _setup()
    assert _verify(build_signed_receipt(signer=SERVICE, mandate=data.mandate), terms, data)


def test_a_receipt_signed_by_another_key_is_refused():
    terms, data = _setup()
    assert not _verify(build_signed_receipt(signer=IMPOSTOR, mandate=data.mandate), terms, data)


def test_a_receipt_claiming_the_service_issuer_with_another_key_is_refused():
    terms, data = _setup()
    body = build_signed_receipt(signer=SERVICE, mandate=data.mandate).receipt.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert not _verify(sign_receipt(IMPOSTOR, body), terms, data)


def test_a_receipt_for_another_mandate_is_refused():
    terms, data = _setup()
    other = PaymentSettlementData.for_agreement(agreement(amount="99"), config())
    assert not _verify(build_signed_receipt(signer=SERVICE, mandate=other.mandate), terms, data)


def test_a_receipt_for_another_agreement_is_refused():
    terms, data = _setup()
    receipt = build_signed_receipt(signer=SERVICE, mandate=data.mandate)
    assert not _verify(receipt, agreement(payer=OTHER), data)


def test_tampering_with_any_signed_field_breaks_the_signature():
    terms, data = _setup()
    signed = build_signed_receipt(signer=SERVICE, mandate=data.mandate).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    signed["receipt"]["ledger"] = "edited"
    assert not _verify(signed, terms, data)
