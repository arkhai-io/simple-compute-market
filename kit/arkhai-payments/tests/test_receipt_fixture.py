"""The receipt fixture reproduces the published conformance vector byte for byte.

This is what makes test receipts trustworthy: the fixture uses the verifier's own
framing and is pinned to what the payments service publishes.
"""

from __future__ import annotations

import json
from pathlib import Path

from market_identity import Ed25519Signer

from market_arkhai_payments import SignedReceipt, receipt_message
from market_arkhai_payments.fixtures import sign_receipt

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "test-vectors" / "payments.json").read_text()
)


def _vector():
    signer = Ed25519Signer(bytes.fromhex(VECTORS["keys"]["service"]))
    expected = SignedReceipt.model_validate(VECTORS["receipt"]["signed"])
    body = expected.receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
    return signer, expected, body


def test_receipt_message_matches_the_published_framing():
    _, _, body = _vector()
    assert receipt_message(body).hex() == VECTORS["receipt"]["message"]


def test_sign_receipt_reproduces_the_published_signature():
    signer, expected, body = _vector()
    assert signer.identity.model_dump(mode="json") == expected.receipt.issuer.model_dump(
        mode="json", by_alias=True
    )
    assert sign_receipt(signer, body) == expected
