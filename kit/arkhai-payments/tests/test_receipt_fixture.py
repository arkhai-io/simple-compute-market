"""The receipt fixture frames and signs exactly as the payments service does.

The published vectors pin the previous wire: their receipt's parts use a hold the
current contract no longer defines. The framing and the signature cover the receipt's
JSON whatever its parts say, so they are reproduced from the raw published body, byte
for byte. A receipt in the current wire is then signed and verified through the same
framing.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from market_identity import Ed25519Signer

from market_arkhai_payments import PaymentSettlementData, receipt_message
from market_arkhai_payments.fixtures import build_signed_receipt, sign_receipt
from market_arkhai_payments.receipts import verify_receipt_signature

from payment_terms import SERVICE, agreement, config

VECTORS = json.loads(
    (Path(__file__).resolve().parents[1] / "test-vectors" / "payments.json").read_text()
)


def test_receipt_message_matches_the_published_framing():
    body = VECTORS["receipt"]["signed"]["receipt"]
    assert receipt_message(body).hex() == VECTORS["receipt"]["message"]


def test_the_fixture_signer_reproduces_the_published_signature():
    signer = Ed25519Signer(bytes.fromhex(VECTORS["keys"]["service"]))
    signed = VECTORS["receipt"]["signed"]
    assert signer.identity.model_dump(mode="json") == signed["receipt"]["issuer"]
    signature = signer.sign(receipt_message(signed["receipt"]))
    assert base64.urlsafe_b64encode(signature).decode().rstrip("=") == signed["proof"]["value"]


def test_a_current_wire_receipt_signs_and_verifies_through_the_same_framing():
    mandate = PaymentSettlementData.for_agreement(agreement(), config()).mandate
    signed = build_signed_receipt(signer=SERVICE, mandate=mandate)
    body = signed.receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert sign_receipt(SERVICE, body) == signed
    assert verify_receipt_signature(signed, SERVICE.identity)
