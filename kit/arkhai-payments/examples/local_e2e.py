#!/usr/bin/env python3
"""Exercise approval, polling, agreement deposit, receipt verification, and reverse locally."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from market_identity import Identity, IdentityScheme  # noqa: E402
from market_arkhai_payments import (  # noqa: E402
    MandatePolicy,
    PaymentsClient,
    PaymentsOptionParams,
    check,
    derive_mandate,
    transaction_id,
    verify_receipt,
)

from market_arkhai_payments.fixtures import dispute_lifecycle  # noqa: E402
from market_deal_lifecycle.terms import LifecycleTerms  # noqa: E402

PAYER = "00000000-0000-4000-8000-000000000011"
PAYEE = "00000000-0000-4000-8000-000000000012"


def local_service_url() -> str:
    value = os.environ.get("PAYMENTS_URL", "http://127.0.0.1:3080")
    host = urlsplit(value).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("local_e2e only accepts a loopback PAYMENTS_URL")
    return value


def local_service_identity() -> Identity:
    identifier = os.environ.get("PAYMENTS_SERVICE_IDENTITY", "")
    if not identifier:
        raise SystemExit("set PAYMENTS_SERVICE_IDENTITY to the service's public receipt identity")
    try:
        return Identity(scheme=IdentityScheme.ED25519, identifier=identifier)
    except ValueError as exc:
        raise SystemExit(
            "PAYMENTS_SERVICE_IDENTITY must be an unpadded base64url Ed25519 public key"
        ) from exc


def main() -> int:
    service_url = local_service_url()
    service_identity = local_service_identity()
    dispute_authority = os.environ.get("ARKHAI_DISPUTE_AUTHORITY", PAYER)
    fee_bps = int(os.environ.get("PAYMENTS_FEE_BPS", "250"))
    accepted_at = int(time.time())
    agreement = {
        "local_e2e": str(uuid4()),
        "accepted_at": datetime.fromtimestamp(accepted_at, timezone.utc).isoformat(),
    }
    option = PaymentsOptionParams(
        payee_account=PAYEE,
        window="P7D",
        deposit_agreement=True,
    )
    policy = MandatePolicy(
        buyer_account=PAYER,
        option=option,
        accepted_at=accepted_at,
        start_utc=accepted_at,
        duration_seconds=0,
        # A fixture amount and asset; production derivation reads the accepted
        # Agreement's.
        amount="1000000",
        asset="USD/6",
        fee_bps=fee_bps,
        lifecycle=LifecycleTerms.model_validate(dispute_lifecycle(dispute_authority)),
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
            service_identity,
            mandate=mandate,
            agreement_json=agreement,
            livemode=False,
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
