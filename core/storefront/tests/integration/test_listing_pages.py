"""Listing pages are ordered by a key no write changes, so a keyset cursor visits each listing once."""

from __future__ import annotations

import base64

from market_core import DomainIdentity
from market_identity import Identity, IdentityScheme

from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from core_storefront.sqlite_client import SQLiteClient

# A deterministic development principal for these tests only; never used on any network.
_SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier=base64.urlsafe_b64encode(bytes([0x11]) * 32).rstrip(b"=").decode(),
)
_DOMAIN = StorefrontDomainBinding(
    offering_mode="vm",
    domain_identity=DomainIdentity("compute.v1"),
    contract_major=1,
    contract_minor=0,
)
#: Every listing shares one creation instant, so only the tie-break orders them.
_CREATED_AT = "2026-08-15T00:00:00Z"


async def _store(tmp_path, count: int) -> SQLiteClient:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    for index in range(count):
        listing_id = f"listing-{index:03d}"
        source = {"pool_id": "pool-a", "listing": listing_id}
        await client.upsert_listing_with_binding(
            binding=StorefrontListingBinding.from_source_envelope(
                listing_id=listing_id,
                site_id="site-a",
                pool_id="pool-a",
                binding=_DOMAIN,
                derivation_key=build_storefront_derivation_key(
                    site_id="site-a", offering_mode="vm", binding=_DOMAIN, source_identity=source
                ),
                source_envelope={"kind": "vm.listing-source.v1", "schema_version": 1, "payload": source},
                last_reconciled_at=_CREATED_AT,
                capacity_backing="backed",
            ),
            status="open",
            created_at=_CREATED_AT,
            updated_at=_CREATED_AT,
            listing_resource={"resource_type": "compute.gpu", "offering_mode": "vm"},
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="https://seller.example",
            seller_principal=_SELLER,
        )
    return client


async def test_a_keyset_cursor_visits_tied_listings_once_while_statuses_change(tmp_path):
    client = await _store(tmp_path, 7)
    seen: list[str] = []
    before = None
    while True:
        page = await client.list_listings(limit=3, before=before)
        if not page:
            break
        seen.extend(row["listing_id"] for row in page)
        for row in page:
            await client.update_listing(
                listing_id=row["listing_id"], status="closed", closed_by="reconciliation"
            )
        before = (page[-1]["created_at"], page[-1]["listing_id"])

    assert seen == [f"listing-{index:03d}" for index in reversed(range(7))]


async def test_rows_tied_on_created_at_come_in_listing_id_order(tmp_path):
    client = await _store(tmp_path, 3)

    rows = await client.list_listings(limit=10)

    assert [row["listing_id"] for row in rows] == ["listing-002", "listing-001", "listing-000"]
