"""Shared values for API-credit negotiation tests against a real SQLite database.

The keys are deterministic development keys for tests only and must never be
used on any network; the token and escrow addresses are placeholders.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch

import apicredits_storefront.utils.config as storefront_config
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig
from market_core.schemas import (
    EscrowProposal,
    ProvisionTerms,
    RateValue,
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer
from tests.listing_bindings import upsert_bound_listing

BUYER_SIGNER = Ed25519Signer(bytes.fromhex("11" * 32))
SELLER_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))
BUYER_PRINCIPAL = BUYER_SIGNER.identity
SELLER_PRINCIPAL = SELLER_SIGNER.identity
TOKEN = "0x" + "01" * 20
ESCROW = "0x" + "11" * 20
LISTING_ID = "L-tok"
SELLER_WALLET = "0x" + "33" * 20
#: The release condition the seeded listing authorizes: the development chain's
#: recipient arbiter paying the seller wallet. The buyer's proposal selects it.
CONDITION = {
    "chain_name": "anvil",
    "arbiter": get_recipient_arbiter("anvil", config_path=str(anvil_address_book_path())),
    "demand_data": {"recipient": SELLER_WALLET},
}


@contextmanager
def anvil_chain():
    """The storefront's anvil chain, naming the address book the condition uses."""
    chain = ChainConfig(
        name="anvil",
        rpc_url="http://anvil.test",
        chain_id=31337,
        alkahest_address_config_path=str(anvil_address_book_path()),
    )
    with patch.dict(storefront_config.CHAINS, {"anvil": chain}, clear=True):
        yield


PAYER_ACCOUNT = "11111111-1111-4111-8111-111111111111"
PAYEE_ACCOUNT = "22222222-2222-4222-8222-222222222222"


def payment_option(rate: int = 100) -> SettlementOption:
    """An Arkhai payments option priced per credit, as a seller publishes one."""
    rates = [RateValue(field="amount", per="credit", value=rate)]
    params = {"payee_account": PAYEE_ACCOUNT, "asset": "USD/2"}
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="arkhai.payments.v1", asset="USD/2", rates=rates, params=params
        ),
        mechanism="arkhai.payments.v1",
        asset="USD/2",
        rates=rates,
        params=params,
    )


def payment_selection(*, expiration_unix: int = 1_900_000_000) -> SettlementSelection:
    option = payment_option()
    return SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=expiration_unix,
        params={"payer_account": PAYER_ACCOUNT},
    )


def proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=ESCROW,
        fields={"token": TOKEN, "amount": amount},
        literal_fields={"token": TOKEN},
        rates=[{"field": "amount", "per": "token", "value": "100"}],
        demand=CONDITION,
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
    """The credits service's site: its quota snapshot and its pool projection."""

    site_names = ["tokens"]

    def __init__(self, available: int = 100) -> None:
        self.available = available
        self.reserved: list[dict] = []

    def site(self, site_id: str) -> "FakeCapacity":
        if site_id not in self.site_names:
            raise KeyError(site_id)
        return self

    async def resource_pool_projection(self):
        return {
            "resource_pools": [
                {
                    "pool_id": "default",
                    "resources": [{"physical_resource_id": "svc-quota"}],
                    "pool_metadata": {
                        "enabled": True,
                        "policy_tags": {
                            "deliverable_modes": ["api_credits"],
                            "advertisable_modes": ["api_credits"],
                            "capacity_backing": "backed",
                        },
                    },
                }
            ]
        }

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
    await upsert_bound_listing(
        client,
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
        demands=[CONDITION],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://test-seller:8002",
        seller_principal=SELLER_PRINCIPAL,
    )


# A deterministic development payments-service key for these tests only; never
# used on any network.
PAYMENTS_SERVICE = Ed25519Signer(bytes.fromhex("55" * 32))
DISPUTE_ACCOUNT = "33333333-3333-4333-8333-333333333333"


class QuotaHolds:
    """The capacity runtime a payment acceptance reserves its quota through."""

    def __init__(self) -> None:
        self.claims: list[dict] = []

    async def reserve(self, _binding, *, claim, deal_ref, ttl_seconds):
        self.claims.append(claim)
        return {
            "capacity_reservation_id": f"alloc-{len(self.claims)}",
            "resource_id": "svc-quota",
            "allocated_units": claim["units"],
            "hold_expires_at": "2099-01-01 00:00",
        }
