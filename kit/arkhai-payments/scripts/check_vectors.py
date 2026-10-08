#!/usr/bin/env python3
"""Validate generated models, JCS identities, and signatures against upstream vectors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_arkhai_payments.canonical import agreement_hash, jcs_bytes  # noqa: E402
from market_arkhai_payments.models import (  # noqa: E402
    ApprovalRequest,
    DealAttachment,
    Mandate,
    SignedReceipt,
    StoredDealAttachment,
)
from market_arkhai_payments.receipts import (  # noqa: E402
    transaction_id,
    verify_receipt_signature,
)

VECTORS = ROOT / "test-vectors" / "payments.json"


def main() -> int:
    vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
    for vector in vectors["mandates"]:
        mandate = Mandate.model_validate(vector["mandate"])
        assert transaction_id(mandate) == vector["id"]

    signed = SignedReceipt.model_validate(vectors["receipt"]["signed"])
    trusted = signed.receipt.issuer.model_dump(mode="json", by_alias=True)
    assert verify_receipt_signature(signed, trusted)

    for vector in vectors["attachments"]:
        DealAttachment.model_validate(vector["request"])
        stored = StoredDealAttachment.model_validate(vector["stored"])
        content = stored.content.root
        canonical = jcs_bytes(content)
        assert hashlib.sha256(canonical).hexdigest() == stored.sha256.root
        assert len(canonical) == stored.size

    for vector in vectors["approvals"]:
        request = ApprovalRequest.model_validate(vector["request"])
        assert transaction_id(request.mandate) == vector["id"]
        assert request.attachments is not None
        assert agreement_hash(request.attachments[0].content.root) == request.mandate.deal.root.root

    print(
        "ok",
        len(vectors["mandates"])
        + 1
        + len(vectors["attachments"])
        + len(vectors["approvals"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
