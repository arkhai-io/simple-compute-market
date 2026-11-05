"""Kept end receipts verify offline against the Agreement, without rewriting evidence."""

import base64
import json

import pytest

from market_identity import (
    Ed25519Signer, Eip191Signer, RequestEnvelope, ResponseEnvelope,
    canonical_body_hash, sign_request, sign_response,
)
from market_deal_lifecycle_contracts.models import (
    EndDeliveryAcknowledgement, EndDeliveryMessage, SignedEndDeliveryReceipt,
)
from market_deal_lifecycle.acknowledgements import (
    verify_end_acknowledgement,
)


def signers(scheme):
    # Deterministic development keys, never for use on a public network.
    if scheme == "ed25519":
        return Ed25519Signer(bytes([1]) * 32), Ed25519Signer(bytes([2]) * 32), Ed25519Signer(bytes([3]) * 32)
    return Eip191Signer("0x" + "01" * 32), Eip191Signer("0x" + "02" * 32), Eip191Signer("0x" + "03" * 32)


def signed_receipt(buyer, seller, *, request_id="request", receipt_at=100):
    request_body = dict(kind="end_delivery", negotiation_id="n", operation_key="op")
    recorded_end = dict(ended_at=receipt_at, actor=buyer.identity.model_dump(mode="json"),
                        cause="payer", source="peer:op", evidence_refs=["request"])
    report = b'{ "site": "original bytes" }\n'
    response_body = dict(negotiation_id="n", operation_key="op", receipt_at=receipt_at,
                         selected_end=recorded_end,
                         delivery=dict(recorded_end=recorded_end, progress="tearing_down", site_reports=[
                             dict(evidence_id="site-report", kind="lease_ended", classification="independent",
                                  recorded_at=100, body=base64.b64encode(report).decode(),
                                  headers={"X-Original-Proof": "original-proof"})]))
    request = sign_request(signer=buyer, envelope=RequestEnvelope(
        role="buyer", principal=buyer.identity, method="POST", operation="lifecycle_peer",
        resource="n", request_id=request_id, timestamp=100, body_hash=canonical_body_hash(request_body)))
    response = sign_response(signer=seller, envelope=ResponseEnvelope(
        role="seller", principal=seller.identity, method="POST", operation="lifecycle_peer",
        resource="n", request_id=request_id, timestamp=101, status=200, body_hash=canonical_body_hash(response_body)))
    receipt = SignedEndDeliveryReceipt(
        request=request, response=response,
        request_body=base64.b64encode(json.dumps(request_body).encode()),
        response_body=base64.b64encode(json.dumps(response_body).encode()))
    return receipt, report


def test_supplied_at_is_refused():
    with pytest.raises(ValueError):
        EndDeliveryMessage(negotiation_id="n", operation_key="op", at=1)


@pytest.mark.parametrize("scheme", ["ed25519", "eip191"])
def test_agreement_principals_bind_both_proofs_and_preserve_exact_report_bytes(scheme):
    buyer, seller, other = signers(scheme)
    receipt, report = signed_receipt(buyer, seller)
    acknowledgement = verify_end_acknowledgement(receipt, negotiation_id="n",
                                                buyer=buyer.identity, seller=seller.identity)
    assert acknowledgement.receipt_at == 100
    assert acknowledgement.delivery.progress == "tearing_down"
    assert acknowledgement.delivery.site_reports[0].body == report
    assert acknowledgement.delivery.site_reports[0].headers == {"X-Original-Proof": "original-proof"}
    for change in [{"buyer": other.identity}, {"seller": other.identity}, {"negotiation_id": "other"}]:
        params = dict(negotiation_id="n", buyer=buyer.identity, seller=seller.identity) | change
        with pytest.raises(ValueError):
            verify_end_acknowledgement(receipt, **params)
    retry, _ = signed_receipt(buyer, seller, request_id="retry", receipt_at=100)
    assert verify_end_acknowledgement(retry, negotiation_id="n", buyer=buyer.identity,
                                     seller=seller.identity).receipt_at == 100


@pytest.mark.parametrize("field,value", [("request_id", "other"), ("status", 201), ("timestamp", 102)])
def test_response_context_and_status_are_signed(field, value):
    buyer, seller, _ = signers("ed25519")
    receipt, _ = signed_receipt(buyer, seller)
    altered = receipt.model_copy(update={"response": receipt.response.model_copy(update={field: value})})
    with pytest.raises(ValueError, match="signature binding"):
        verify_end_acknowledgement(altered, negotiation_id="n", buyer=buyer.identity, seller=seller.identity)


def test_claim_embedding_preserves_the_interface_owned_claim_without_rewriting():
    buyer, seller, _ = signers("ed25519")
    receipt, _ = signed_receipt(buyer, seller)
    data = json.loads(receipt.response_body)
    claim = {"agreement": "0" * 64,
             "claim": {"kind": "delivery_end", "ended_at": 100, "delivered": True, "cause": "payer"},
             "signer": seller.identity.model_dump(mode="json"), "proof": receipt.response.proof.model_dump(mode="json")}
    data["signed_delivery_end_claim"] = claim
    assert EndDeliveryAcknowledgement.model_validate(data).signed_delivery_end_claim == claim
