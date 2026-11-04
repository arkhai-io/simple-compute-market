#!/usr/bin/env python3
"""Run the installed-resource conformance replay from a source checkout, then
verify the historical publication's raw signing and hash framing.

The current publication is replayed through the shared authority fixture by
``market_arkhai_payments.fixtures.conformance``. The historical publication is a
separate regression: its obsolete mandates, receipt and approvals are refused by the
current models, while their raw JCS transaction identities, receipt signing bytes
and signature, approval commitments and attachment hashes still verify.
"""

from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_identity import Identity, SignatureProof, get_identity_verifier  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from market_arkhai_payments.canonical import agreement_hash, jcs_bytes, jcs_sha256  # noqa: E402
from market_arkhai_payments.fixtures.conformance import main as replay_current  # noqa: E402
from market_arkhai_payments.models import (  # noqa: E402
    ApprovalRequest,
    DealAttachment,
    Mandate,
    SignedReceipt,
    StoredDealAttachment,
)
from market_arkhai_payments.receipts import receipt_message  # noqa: E402

HISTORICAL = ROOT / "test-vectors" / "historical-payments.json"


def _signature(body: dict, proof_value: dict, message: bytes) -> None:
    issuer = Identity.model_validate(body["issuer"])
    proof = SignatureProof.model_validate(proof_value)
    assert get_identity_verifier(issuer.scheme).verify_signature(issuer, message, proof.to_bytes())


def _refused(model: type[Mandate | SignedReceipt | ApprovalRequest], value: object) -> None:
    try:
        model.model_validate(value)
    except ValidationError:
        return
    raise AssertionError(f"the current {model.__name__} accepts the previous wire")


def check_historical(vectors: dict) -> None:
    for vector in vectors["mandates"]:
        assert jcs_sha256(vector["mandate"]) == vector["id"]
        _refused(Mandate, vector["mandate"])
    signed = vectors["receipt"]["signed"]
    message = receipt_message(signed["receipt"])
    assert message.hex() == vectors["receipt"]["message"]
    _signature(signed["receipt"], signed["proof"], message)
    _refused(SignedReceipt, signed)
    for vector in vectors["attachments"]:
        DealAttachment.model_validate(vector["request"])
        stored = StoredDealAttachment.model_validate(vector["stored"])
        canonical = jcs_bytes(stored.content.root)
        assert hashlib.sha256(canonical).hexdigest() == stored.sha256.root
        assert len(canonical) == stored.size
    for vector in vectors["approvals"]:
        request = vector["request"]
        assert jcs_sha256(request["mandate"]) == vector["id"]
        attachment = DealAttachment.model_validate(request["attachments"][0])
        assert agreement_hash(attachment.content.root) == request["mandate"]["deal"]
        _refused(ApprovalRequest, request)


def main() -> int:
    status = replay_current()
    if status:
        return status
    check_historical(json.loads(HISTORICAL.read_text(encoding="utf-8")))
    print("historical raw framing verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
