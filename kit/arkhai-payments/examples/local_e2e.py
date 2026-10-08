#!/usr/bin/env python3
"""Exercise approval, polling, agreement deposit, receipt verification, and reverse locally."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_identity import create_signer  # noqa: E402
from market_arkhai_payments import (  # noqa: E402
    MandatePolicy,
    PaymentsClient,
    PaymentsOptionParams,
    check,
    derive_mandate,
    transaction_id,
    verify_receipt,
)

PAYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"


def local_service_url() -> str:
    value = os.environ.get("PAYMENTS_URL", "http://127.0.0.1:3080")
    host = urlsplit(value).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("local_e2e only accepts a loopback PAYMENTS_URL")
    return value


def local_service_identity():
    key = os.environ.get("RECEIPT_SIGNING_KEY", "")
    if re.fullmatch(r"[0-9a-fA-F]{64}", key):
        seed = bytes.fromhex(key)
    else:
        try:
            seed = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
        except (ValueError, binascii.Error) as exc:
            raise SystemExit("set RECEIPT_SIGNING_KEY to the local service's seed") from exc
    if len(seed) != 32:
        raise SystemExit("RECEIPT_SIGNING_KEY must encode a 32-byte Ed25519 seed")
    return create_signer("ed25519", seed).identity


def main() -> int:
    service_url = local_service_url()
    dispute_authority = os.environ.get("ARKHAI_DISPUTE_AUTHORITY", PAYER)
    fee_bps = int(os.environ.get("PAYMENTS_FEE_BPS", "250"))
    accepted_at = int(time.time())
    agreement = {
        "local_e2e": str(uuid4()),
        "accepted_at": datetime.fromtimestamp(accepted_at, timezone.utc).isoformat(),
    }
    option = PaymentsOptionParams(
        payee_account=PAYEE,
        asset="USD/2",
        window="P7D",
        deposit_agreement=True,
    )
    policy = MandatePolicy(
        buyer_account=PAYER,
        option=option,
        accepted_at=accepted_at,
        start_utc=accepted_at,
        duration_seconds=0,
        amount="100",
        asset="USD/2",
        fee_bps=fee_bps,
        dispute_authority=dispute_authority,
    )
    mandate = derive_mandate(agreement, policy)
    check(mandate, agreement, policy)
    identifier = transaction_id(mandate)

    with PaymentsClient(service_url, development_account=PAYER) as buyer:
        buyer.approve(mandate)
        buyer.poll(identifier, timeout=15, interval=0.25)
    with PaymentsClient(service_url, development_account=PAYEE) as seller:
        snapshot = seller.poll(identifier, timeout=15, interval=0.25)
        signed_receipt = snapshot.snapshot.receipt
        if not verify_receipt(
            signed_receipt,
            local_service_identity(),
            mandate=mandate,
            agreement_json=agreement,
        ):
            raise SystemExit("service receipt did not verify against this Agreement")
        deposited = seller.ensure_agreement_attached(identifier, agreement, option)
        if deposited is None:
            raise SystemExit("seller deposit setting was not applied")
        reversed_event = seller.reverse(identifier)
        if reversed_event.event.kind.value != "reverse":
            raise SystemExit("service returned an unexpected reverse event")
    print(f"approved, receipt verified, Agreement deposited, and reversed {identifier}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
