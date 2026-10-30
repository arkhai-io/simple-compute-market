#!/usr/bin/env python3
"""Check the kit's framing against the payments service's published vectors.

The vectors are the service's previous publication; schema/SOURCE.md says why. Their
mandates and receipt use the previous wire, which the current models refuse, and this
check asserts that refusal. What does not depend on a part's shape is checked over the
raw published JSON: the JCS transaction identity, the receipt's signing frame and its
Ed25519 signature, and attachment hashing.
"""

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
    get_identity_verifier,
)
from pydantic import ValidationError  # noqa: E402

from market_arkhai_payments.canonical import agreement_hash, jcs_bytes, jcs_sha256  # noqa: E402
from market_arkhai_payments.models import (  # noqa: E402
    ApprovalRequest,
    DealAttachment,
    Mandate,
    SignedReceipt,
    StoredDealAttachment,
)
from market_arkhai_payments.receipts import receipt_message  # noqa: E402

VECTORS = ROOT / "test-vectors" / "payments.json"


def main() -> int:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    for vector in vectors["mandates"]:
        assert jcs_sha256(vector["mandate"]) == vector["id"]
        _refused(Mandate, vector["mandate"])

    signed = vectors["receipt"]["signed"]
    message = receipt_message(signed["receipt"])
    assert message.hex() == vectors["receipt"]["message"]
    issuer = Identity.model_validate(signed["receipt"]["issuer"])
    proof = SignatureProof.model_validate(signed["proof"])
    assert get_identity_verifier(issuer.scheme).verify_signature(issuer, message, proof.to_bytes())
    _refused(SignedReceipt, signed)

    for vector in vectors["attachments"]:
        DealAttachment.model_validate(vector["request"])
        stored = StoredDealAttachment.model_validate(vector["stored"])
        content = stored.content.root
        canonical = jcs_bytes(content)
        assert hashlib.sha256(canonical).hexdigest() == stored.sha256.root
        assert len(canonical) == stored.size

    for vector in vectors["approvals"]:
        request = vector["request"]
        assert jcs_sha256(request["mandate"]) == vector["id"]
        attachment = DealAttachment.model_validate(request["attachments"][0])
        assert agreement_hash(attachment.content.root) == request["mandate"]["deal"]
        _refused(ApprovalRequest, request)

    print(
        "ok",
        len(vectors["mandates"])
        + 1
        + len(vectors["attachments"])
        + len(vectors["approvals"]),
    )
    return 0


def _refused(model: type[Mandate | SignedReceipt | ApprovalRequest], value: object) -> None:
    try:
        model.model_validate(value)
    except ValidationError:
        return
    raise AssertionError(f"the current {model.__name__} accepts the previous wire")


if __name__ == "__main__":
    raise SystemExit(main())
