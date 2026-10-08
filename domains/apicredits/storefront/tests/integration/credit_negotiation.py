"""Shared values for API-credit negotiation tests against a real SQLite database.

The keys are deterministic development keys for tests only and must never be
used on any network; the token and escrow addresses are placeholders.
"""

from __future__ import annotations

from datetime import datetime

from market_core.schemas import (
    EscrowProposal,
    ProvisionTerms,
)
from market_identity import Ed25519Signer

BUYER_SIGNER = Ed25519Signer(bytes.fromhex("11" * 32))
SELLER_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))
BUYER_PRINCIPAL = BUYER_SIGNER.identity
SELLER_PRINCIPAL = SELLER_SIGNER.identity
TOKEN = "0x" + "01" * 20
ESCROW = "0x" + "11" * 20
LISTING_ID = "L-tok"


def proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=ESCROW,
        fields={"token": TOKEN, "amount": amount},
        literal_fields={"token": TOKEN},
        rates=[{"field": "amount", "per": "token", "value": "100"}],
        expiration_unix=1_800_000_000,
    )


def terms(quantity=3, key_mode="new", key_id=None) -> ProvisionTerms:
    key: dict = {"mode": key_mode}
    if key_id:
        key["key_id"] = key_id
    return ProvisionTerms(
        kind="api_credits.v1",
        version=1,
        payload={"quantity": quantity, "key": key},
    )


class FakeCapacity:
    def __init__(self, available: int = 100) -> None:
        self.available = available
        self.reserved: list[dict] = []

    async def snapshot(self):
        return [
            {
                "resource_id": "svc-quota",
                "resource_type": "api_credits",
                "available_units": self.available,
                "total_units": 1000,
                "state": "available",
            }
        ]

    async def reserve(self, *, claim=None, deal_ref=None, ttl_seconds=None):
        self.reserved.append(
            {
                "claim": claim,
                "deal_ref": deal_ref,
                "ttl_seconds": ttl_seconds,
            }
        )
        return {
            "capacity_reservation_id": f"alloc-{len(self.reserved)}",
            "resource_id": "svc-quota",
            "allocated_units": (claim or {}).get("units"),
            "hold_expires_at": "2099-01-01 00:00",
        }


async def seed_listing(client) -> None:
    """Open the one quota-backed listing these tests negotiate."""
    await client.upsert_listing(
        listing_id="L-tok",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        listing_resource={
            "kind": "api_credits.v1",
            "service_name": "Acme Inference",
            "openapi_url": "https://api.acme.example/openapi.json",
            "base_url": "https://api.acme.example",
            "resource_id": "svc-quota",
            "capacity_site_id": "tokens",
            "offering_mode": "api_credits",
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": ESCROW,
                "literal_fields": {"token": TOKEN},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
        settlement_options=[],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://test-seller:8002",
        seller_principal=SELLER_PRINCIPAL,
    )
