"""Test fixtures for consumers of the Arkhai payments kit.

The receipt fixture shares the kit verifier's framing and is proven against the
published conformance vector, so tests never sign receipts any other way.
"""

from market_deal_lifecycle.terms import LifecycleTerms
from market_identity import Ed25519Signer

from market_arkhai_payments.fixtures.authority import PaymentsAuthority, sign_snapshot, snapshot_message
from market_arkhai_payments.fixtures.payments_client import FakePaymentsClient
from market_arkhai_payments.fixtures.receipts import (
    build_signed_receipt,
    receipt_parts,
    sign_receipt,
)

def dispute_lifecycle(account: str) -> dict:
    """Public development terms for controlled payment fixtures, never a live authority."""
    return LifecycleTerms.model_validate({
        "adjudication": {
            "version": 1,
            "dispute": {
                "interface": "example.dispute.v1",
                "origin": "https://dispute.example",
                "account": account,
                "record_key": "ed25519:" + Ed25519Signer(bytes(range(32))).identity.identifier,
                "params": {},
            },
            "dispute_window_seconds": 604800,
            "case_hold_max_seconds": None,
        },
    }).model_dump(mode="json", exclude_none=False, exclude_unset=True)


__all__ = [
    "PaymentsAuthority", "FakePaymentsClient", "build_signed_receipt", "receipt_parts",
    "sign_receipt", "sign_snapshot", "snapshot_message", "dispute_lifecycle",
]
