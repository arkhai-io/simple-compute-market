"""Signed payments receipts for tests, framed exactly as the payments service frames them."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

from market_identity import Signer

from market_arkhai_payments.models import Mandate, SignedReceipt
from market_arkhai_payments.receipts import receipt_message, transaction_id


def sign_receipt(signer: Signer, receipt: Mapping[str, Any]) -> SignedReceipt:
    """Sign one receipt body with an injected signer; no key material lives here."""

    signature = signer.sign(receipt_message(receipt))
    return SignedReceipt.model_validate(
        {
            "receipt": dict(receipt),
            "proof": {
                "scheme": signer.identity.scheme.value,
                "value": base64.urlsafe_b64encode(signature).decode().rstrip("="),
            },
        }
    )


def receipt_parts(mandate: Mandate | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return receipt parts for a mandate with the fee rounded down per part."""

    wire = Mandate.model_validate(mandate).model_dump(mode="json", by_alias=True, exclude_none=True)
    bps = int(wire["fee"]["bps"])
    parts = []
    for part in wire["parts"]:
        gross = int(part["amount"])
        fee = gross * bps // 10_000
        parts.append(
            {
                "asset": part["asset"],
                "gross": str(gross),
                "fee": str(fee),
                "net": str(gross - fee),
                "hold": part["hold"],
            }
        )
    return parts


def build_signed_receipt(
    *,
    signer: Signer,
    mandate: Mandate | Mapping[str, Any],
    approved_at: int = 1_800_000_000,
    ledger: str = "fixture",
) -> SignedReceipt:
    """A receipt for exactly this mandate, as the payments service would sign it."""

    parsed = Mandate.model_validate(mandate)
    wire = parsed.model_dump(mode="json", by_alias=True, exclude_none=True)
    return sign_receipt(
        signer,
        {
            "transaction": transaction_id(parsed),
            "deal": wire["deal"],
            "from": wire["from"],
            "to": wire["to"],
            "ledger": ledger,
            "parts": receipt_parts(parsed),
            "approvedAt": approved_at,
            "issuer": signer.identity.model_dump(mode="json"),
        },
    )


__all__ = ["build_signed_receipt", "receipt_parts", "sign_receipt"]
