"""Kept end receipts verify offline against the Agreement, without rewriting evidence."""

import asyncio
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
    read_without_adapter, receipt_time, verify_end_acknowledgement,
)


class Receipts:
    def __init__(self):
        self.values = {}

    async def get_or_record(self, negotiation_id, operation_key, digest, received_at):
        previous = self.values.setdefault((negotiation_id, operation_key), (digest, received_at))
        if previous[0] != digest:
            raise ValueError("receipt retry changed content")
        return previous[1]


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


def test_supplied_at_is_refused_and_retry_keeps_the_first_receipt():
    with pytest.raises(ValueError):
        EndDeliveryMessage(negotiation_id="n", operation_key="op", at=1)
    request, store = EndDeliveryMessage(negotiation_id="n", operation_key="op"), Receipts()
    async def drive():
        assert await receipt_time(request, 100, store) == 100
        assert await receipt_time(request, 110, store) == 100
    asyncio.run(drive())


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


def test_read_without_adapter_does_not_hide_evidence_or_invent_authority_state():
    buyer, seller, _ = signers("ed25519")
    receipt, report = signed_receipt(buyer, seller)
    acknowledgement = verify_end_acknowledgement(receipt, negotiation_id="n",
                                                buyer=buyer.identity, seller=seller.identity)
    read = read_without_adapter("n", "example.no-adapter", acknowledgement.delivery)
    assert read.authority.outcome.status == "rejected"
    assert "example.no-adapter" in read.authority.outcome.reason
    assert read.authority.state is None and read.authority.events == []
    assert read.delivery.site_reports[0].body == report


def test_concrete_claim_embedding_fails_closed_until_its_owning_contract_is_available():
    buyer, seller, _ = signers("ed25519")
    receipt, _ = signed_receipt(buyer, seller)
    data = json.loads(receipt.response_body)
    data["signed_delivery_end_claim"] = {"unpublished": True}
    with pytest.raises(ValueError):
        EndDeliveryAcknowledgement.model_validate(data)
