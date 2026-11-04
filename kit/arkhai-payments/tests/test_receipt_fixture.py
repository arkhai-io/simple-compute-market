"""The receipt fixture frames and signs exactly as the payments service does.

Current and historical producer publications pin raw receipt framing and deterministic
fixture signatures. Current receipts also pass the strict generated models.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest

from market_identity import Ed25519Signer

from market_arkhai_payments import PaymentSettlementData, receipt_message
from market_arkhai_payments.canonical import wire_json
from market_arkhai_payments.fixtures import build_signed_receipt, sign_receipt
from market_arkhai_payments.models import SignedReceipt
from market_arkhai_payments.receipts import verify_receipt_signature

from payment_terms import SERVICE, agreement, config

# Published deterministic development signing fixtures; never use on a public network.
VECTORS = [
    json.loads((Path(__file__).resolve().parents[1] / "test-vectors" / name).read_text())
    for name in ("payments.json", "historical-payments.json")
]


@pytest.mark.parametrize("vectors", VECTORS)
def test_receipt_message_matches_the_published_framing(vectors):
    body = vectors["receipt"]["signed"]["receipt"]
    assert receipt_message(body).hex() == vectors["receipt"]["message"]


@pytest.mark.parametrize("vectors", VECTORS)
def test_the_fixture_signer_reproduces_the_published_signature(vectors):
    signer = Ed25519Signer(bytes.fromhex(vectors["keys"]["service"]))
    signed = vectors["receipt"]["signed"]
    assert signer.identity.model_dump(mode="json") == signed["receipt"]["issuer"]
    signature = signer.sign(receipt_message(signed["receipt"]))
    assert base64.urlsafe_b64encode(signature).decode().rstrip("=") == signed["proof"]["value"]


def test_an_explicit_null_optional_in_a_receipt_verifies_as_its_normalized_body():
    # A receipt part's `rate` is optional and the schema does not allow null. The
    # models accept an inserted null and normalize it away, so the signature over
    # the published body still verifies and the parsed receipt equals the signed one.
    vectors = VECTORS[0]
    signed = copy.deepcopy(vectors["receipt"]["signed"])
    trusted = Ed25519Signer(bytes.fromhex(vectors["keys"]["service"])).identity
    assert all("rate" not in part for part in signed["receipt"]["parts"])
    padded = copy.deepcopy(signed)
    for part in padded["receipt"]["parts"]:
        part["rate"] = None
    assert receipt_message(padded["receipt"]) != receipt_message(signed["receipt"])
    assert verify_receipt_signature(padded, trusted)
    assert SignedReceipt.model_validate(padded) == SignedReceipt.model_validate(signed)
    assert wire_json(SignedReceipt.model_validate(padded)) == signed


def test_a_current_wire_receipt_signs_and_verifies_through_the_same_framing():
    mandate = PaymentSettlementData.for_agreement(agreement(), config()).mandate
    signed = build_signed_receipt(signer=SERVICE, mandate=mandate)
    body = signed.receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert sign_receipt(SERVICE, body) == signed
    assert verify_receipt_signature(signed, SERVICE.identity)
