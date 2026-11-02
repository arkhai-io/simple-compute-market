#!/usr/bin/env python3
"""Verify current producer conformance and historical raw signing/hash framing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_identity import (  # noqa: E402
    Identity,
    SignatureProof,
    frame_fields,
    get_identity_verifier,
)
from pydantic import ValidationError  # noqa: E402

from market_arkhai_payments.canonical import agreement_hash, jcs_bytes, jcs_sha256, wire_json  # noqa: E402
from market_arkhai_payments.models import (  # noqa: E402
    ApprovalRequest,
    DealAttachment,
    EventRequest,
    Mandate,
    SignedReceipt,
    SignedTransactionSnapshot,
    StoredDealAttachment,
    StoredEvent,
)
from market_arkhai_payments.receipts import receipt_message, transaction_id, verify_receipt_signature  # noqa: E402

VECTORS = ROOT / "test-vectors" / "payments.json"
HISTORICAL = ROOT / "test-vectors" / "historical-payments.json"


def _signature(body: dict, proof_value: dict, message: bytes) -> None:
    issuer = Identity.model_validate(body["issuer"])
    proof = SignatureProof.model_validate(proof_value)
    assert get_identity_verifier(issuer.scheme).verify_signature(issuer, message, proof.to_bytes())


def _receipt(signed: dict, expected_message: str | None = None) -> None:
    parsed = SignedReceipt.model_validate(signed)
    assert wire_json(parsed) == signed
    message = receipt_message(parsed.receipt)
    if expected_message is not None:
        assert message.hex() == expected_message
    assert verify_receipt_signature(parsed, signed["receipt"]["issuer"])


def _snapshot(vector: dict, mandate: dict) -> None:
    signed = vector["signed"]
    parsed = SignedTransactionSnapshot.model_validate(signed)
    assert wire_json(parsed) == signed
    assert parsed.snapshot.transaction.root == transaction_id(mandate)
    assert parsed.snapshot.receipt.receipt.transaction == parsed.snapshot.transaction
    message = frame_fields(("arkhai.payments.snapshot.v1", jcs_sha256(parsed.snapshot)))
    assert message.hex() == vector["message"]
    _signature(signed["snapshot"], signed["proof"], message)
    _receipt(signed["snapshot"]["receipt"])


def _attachments(vectors: dict) -> None:
    for vector in vectors["attachments"]:
        DealAttachment.model_validate(vector["request"])
        stored = StoredDealAttachment.model_validate(vector["stored"])
        canonical = jcs_bytes(stored.content.root)
        assert hashlib.sha256(canonical).hexdigest() == stored.sha256.root
        assert len(canonical) == stored.size


def check_current(vectors: dict) -> None:
    for vector in vectors["mandates"]:
        mandate = Mandate.model_validate(vector["mandate"])
        assert wire_json(mandate) == vector["mandate"]
        assert transaction_id(mandate) == vector["id"] == jcs_sha256(vector["mandate"])
    _receipt(vectors["receipt"]["signed"], vectors["receipt"]["message"])
    _attachments(vectors)
    for vector in vectors["approvals"]:
        request = ApprovalRequest.model_validate(vector["request"])
        assert wire_json(request) == vector["request"]
        assert transaction_id(request.mandate) == vector["id"]
        assert request.attachments is not None
        assert agreement_hash(request.attachments[0].content.root) == wire_json(request.mandate.deal)
    for vector in vectors["snapshots"]:
        _snapshot(vector, vector["mandate"])
    for scenario in vectors["scenarios"]:
        mandate = scenario["mandate"]
        _receipt(scenario["receipt"])
        assert scenario["receipt"]["receipt"]["transaction"] == transaction_id(mandate)
        for step in scenario["steps"]:
            _snapshot(step["snapshot"], mandate)
            if "request" in step:
                request = EventRequest.model_validate(step["request"])
                event = StoredEvent.model_validate(step["expectedEvent"])
                assert wire_json(request) == step["request"]
                assert wire_json(event) == step["expectedEvent"]


def check_historical(vectors: dict) -> None:
    for vector in vectors["mandates"]:
        assert jcs_sha256(vector["mandate"]) == vector["id"]
        _refused(Mandate, vector["mandate"])
    signed = vectors["receipt"]["signed"]
    message = receipt_message(signed["receipt"])
    assert message.hex() == vectors["receipt"]["message"]
    _signature(signed["receipt"], signed["proof"], message)
    _refused(SignedReceipt, signed)
    _attachments(vectors)
    for vector in vectors["approvals"]:
        request = vector["request"]
        assert jcs_sha256(request["mandate"]) == vector["id"]
        attachment = DealAttachment.model_validate(request["attachments"][0])
        assert agreement_hash(attachment.content.root) == request["mandate"]["deal"]
        _refused(ApprovalRequest, request)


def _refused(model: type[Mandate | SignedReceipt | ApprovalRequest], value: object) -> None:
    try:
        model.model_validate(value)
    except ValidationError:
        return
    raise AssertionError(f"the current {model.__name__} accepts the previous wire")


def main() -> int:
    check_current(json.loads(VECTORS.read_text(encoding="utf-8")))
    check_historical(json.loads(HISTORICAL.read_text(encoding="utf-8")))
    print("current producer vectors and historical raw framing verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
