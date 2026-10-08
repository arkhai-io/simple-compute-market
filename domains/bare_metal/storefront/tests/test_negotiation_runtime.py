"""Bare metal's hooks onto the kit negotiation runtime, below the HTTP routes."""

from __future__ import annotations

import json
import time
from typing import Any

from market_identity import Eip191Signer
from market_policy.listing_source import ListingSourceVerdict
from market_storefront_kit import TradingPause

from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.negotiation import default_seller_round_hook
from arkhai_bare_metal_storefront.negotiation_runtime import (
    build_bare_metal_negotiation_runtime,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

BUYER = Eip191Signer(bytes.fromhex("22" * 32)).identity
SELLER = Eip191Signer(bytes.fromhex("11" * 32)).identity
ESCROW = "0x1111111111111111111111111111111111111111"
TOKEN = "0x2222222222222222222222222222222222222222"
WALLET = "0x3333333333333333333333333333333333333333"
TERMS = {
    "kind": "bare_metal.v2",
    "version": 1,
    "payload": {
        "duration_seconds": 3600,
        "access_method": "ssh",
        "ssh_public_key": "ssh-ed25519 buyer-key",
    },
}


async def _matches(_listing_id: str) -> ListingSourceVerdict:
    return ListingSourceVerdict("matches")


async def _listing(db: SQLiteClient) -> None:
    await db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=SELLER,
        storefront_url="http://seller:8000",
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": ESCROW,
                "literal_fields": {"token": TOKEN},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }
        ],
    )


async def test_an_accepted_escrow_is_planned_from_verifications_inputs(tmp_path) -> None:
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=get_market_domain_contract())
    await _listing(db)
    calls: list[dict[str, Any]] = []

    def builder(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "settlement_plan": {
                "buyer_principal": BUYER.model_dump(mode="json"),
                "seller_principal": SELLER.model_dump(mode="json"),
                "obligations": [],
            }
        }

    runtime = build_bare_metal_negotiation_runtime(
        domain=get_market_domain_contract(),
        seller_principal=SELLER,
        round_hook=default_seller_round_hook(),
        listing_source_check=_matches,
        trading_pause=TradingPause(),
        plan_builder=builder,
        accepted_obligation_dispatch={},
        seller_wallet_address=WALLET,
        chain_config_paths={"anvil": "/addresses.json"},
    )
    opened = await runtime.start(
        repository=db,
        listing_id="listing-1",
        buyer_principal=BUYER,
        seller_principal=SELLER,
        actor_principal=BUYER,
        proposal={
            "chain_name": "anvil",
            "escrow_address": ESCROW,
            "fields": {"amount": "100", "token": TOKEN},
            "literal_fields": {"token": TOKEN},
            "expiration_unix": int(time.time()) + 3600,
        },
        terms=TERMS,
        seller_agent_url="http://seller:8000",
        buyer_agent_url="https://buyer.example",
    )

    assert opened["action"] == "accept"
    (call,) = calls
    assert call["seller_wallet_address"] == WALLET
    assert call["chain_config_paths"] == {"anvil": "/addresses.json"}
    assert call["duration_seconds"] == 3600
    # The response returns, and the thread records, the terms as the buyer sent them.
    assert opened["accepted_provision_terms"] == TERMS
    thread = await db.load_negotiation_thread_row(negotiation_id=opened["negotiation_id"])
    recorded = thread["provision_terms"]
    assert (json.loads(recorded) if isinstance(recorded, str) else recorded) == TERMS
