from __future__ import annotations

from datetime import datetime

import pytest
from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
)

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.migrations import migrate_storefront_database
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import TEST_MARKETPLACE_SIGNER


@pytest.mark.asyncio
async def test_listing_round_trips_canonical_publication_clauses(tmp_path) -> None:
    migrate_storefront_database(tmp_path / "storefront.db")
    db = SQLiteClient(db_path=str(tmp_path / "storefront.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))
    now = datetime.now().isoformat()
    clauses = [
        {
            "mechanism": "example.rated.v1",
            "asset": "usd",
            "rate": "2",
            "per": "hour",
            "mechanism_input": {"profile": "standard", "window": "P7D"},
        }
    ]

    await db.upsert_listing(
        listing_id="listing-with-publication-clauses",
        status="open",
        created_at=now,
        updated_at=now,
        listing_resource={
            "resource_type": "compute",
            "resource_id": "resource-1",
            "gpu_model": "H200",
            "gpu_count": 1,
            "region": "California, US",
            "sla": 99.0,
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller.test",
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
        accepted_escrows=[],
        settlement_options=[],
        publication_clauses=clauses,
        demands=[],
    )

    stored = await db.load_listing(listing_id="listing-with-publication-clauses")

    assert stored is not None
    assert stored["publication_clauses"] == clauses


@pytest.mark.asyncio
async def test_bound_listing_round_trips_explicit_accepted_escrows(tmp_path) -> None:
    domain = build_vm_storefront_domain()
    registry = build_vm_storefront_registry(domain)
    binding = registry.resolve_mode("vm").binding
    assert registry.resolve(binding) is domain
    migrate_storefront_database(tmp_path / "storefront.db")
    db = SQLiteClient(str(tmp_path / "storefront.db"), registry=registry)
    # Development escrow and token addresses; never used on a public network.
    explicit = [{
        "chain_name": "base_sepolia",
        "escrow_address": "0x" + "11" * 20,
        "literal_fields": {"token": "0x" + "22" * 20},
        "rates": [{"field": "amount", "per": "hour", "value": "999"}],
    }]
    source = {
        "kind": "compute.listing_source",
        "schema_version": 1,
        "payload": {
            "site_id": "site-1",
            "pool_id": "pool-1",
            "gpu_count": 1,
        },
    }
    listing_binding = StorefrontListingBinding.from_source_envelope(
        listing_id="lst2",
        site_id="site-1",
        binding=binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-1",
            offering_mode=binding.offering_mode,
            binding=binding,
            source_identity=source,
        ),
        source_envelope=source,
        last_reconciled_at="2026-08-15T00:00:00Z",
        capacity_backing="backed",
        pool_id="pool-1",
    )
    await db.upsert_listing_with_binding(
        binding=listing_binding, status="open",
        created_at="2026-01-01", updated_at="2026-01-01",
        listing_resource={
            "offering_mode": "vm",
            "pool_id": "pool-1",
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 0.99,
            "region": "California, US",
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller.test",
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
        accepted_escrows=explicit,
    )

    row = await db.load_listing(listing_id="lst2")
    assert row["accepted_escrows"] == explicit
    assert await db.load_listing_binding(listing_id="lst2") == listing_binding
