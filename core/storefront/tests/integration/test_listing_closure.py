"""Closure provenance on the listing row: who closed it, and who may reopen it.

These run against a real SQLite database because the rule is enforced at the
listing write inside one transaction, alongside the closure-reason triggers.
"""

from __future__ import annotations

import base64
import sqlite3
from datetime import UTC, datetime

import pytest

from market_core import DomainIdentity
from market_identity import Identity, IdentityScheme
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from core_storefront.sqlite_client import (
    SellerClosedListingError,
    SQLiteClient,
    write_listing_update,
)

_SELLER = Identity(
    scheme=IdentityScheme.ED25519,
    identifier=base64.urlsafe_b64encode(bytes([0x11]) * 32).rstrip(b"=").decode(),
)


def _binding(listing_id: str = "listing-a") -> StorefrontListingBinding:
    domain = StorefrontDomainBinding(
        offering_mode="vm",
        domain_identity=DomainIdentity("compute.v1"),
        contract_major=1,
        contract_minor=0,
    )
    source = {"pool_id": "pool-a", "listing": listing_id}
    return StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id="site-a",
        pool_id="pool-a",
        binding=domain,
        derivation_key=build_storefront_derivation_key(
            site_id="site-a",
            offering_mode="vm",
            binding=domain,
            source_identity=source,
        ),
        source_envelope={
            "kind": "vm.listing-source.v1",
            "schema_version": 1,
            "payload": source,
        },
        last_reconciled_at=datetime.now(UTC).isoformat(),
        capacity_backing="backed",
    )


async def _persist(client: SQLiteClient, listing_id: str = "listing-a") -> str:
    binding = _binding(listing_id)
    await client.upsert_listing_with_binding(
        binding=binding,
        status="open",
        created_at="2026-08-15T00:00:00Z",
        updated_at="2026-08-15T00:00:00Z",
        listing_resource={"resource_type": "compute.gpu", "offering_mode": "vm"},
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="https://seller.example",
        seller_principal=_SELLER,
    )
    return binding.listing_id


@pytest.fixture
def client(tmp_path) -> SQLiteClient:
    return SQLiteClient(str(tmp_path / "storefront.db"))


async def test_close_requires_a_reason_and_the_listing_reports_it(client):
    listing_id = await _persist(client)
    with pytest.raises(ValueError, match="closed_by"):
        await client.update_listing(listing_id=listing_id, status="closed")
    with pytest.raises(ValueError, match="closed_by"):
        await client.update_listing(
            listing_id=listing_id, status="open", closed_by="seller"
        )

    assert (await client.load_listing(listing_id=listing_id))["closed_by"] is None
    await client.update_listing(
        listing_id=listing_id, status="closed", closed_by="reconciliation"
    )
    assert (await client.load_listing(listing_id=listing_id))["closed_by"] == (
        "reconciliation"
    )
    (row,) = await client.list_listings(status="closed")
    assert row["closed_by"] == "reconciliation"


async def test_reconciliation_cannot_reopen_a_seller_close(client):
    listing_id = await _persist(client)
    await client.update_listing(listing_id=listing_id, status="closed", closed_by="seller")

    with pytest.raises(SellerClosedListingError, match="closed by its seller"):
        await client.update_listing(listing_id=listing_id, status="open")
    with pytest.raises(SellerClosedListingError):
        await client.update_listing(
            listing_id=listing_id, status="open", reopened_by="reconciliation"
        )

    row = await client.load_listing(listing_id=listing_id)
    assert (row["status"], row["closed_by"]) == ("closed", "seller")


async def test_seller_reopen_clears_the_reason(client):
    listing_id = await _persist(client)
    await client.update_listing(listing_id=listing_id, status="closed", closed_by="seller")

    await client.update_listing(listing_id=listing_id, status="open", reopened_by="seller")

    row = await client.load_listing(listing_id=listing_id)
    assert (row["status"], row["closed_by"]) == ("open", None)


async def test_reconciliation_reopens_its_own_close(client):
    listing_id = await _persist(client)
    await client.update_listing(
        listing_id=listing_id, status="closed", closed_by="reconciliation"
    )

    await client.update_listing(
        listing_id=listing_id, status="open", reopened_by="reconciliation"
    )

    row = await client.load_listing(listing_id=listing_id)
    assert (row["status"], row["closed_by"]) == ("open", None)


async def test_reconciliation_close_keeps_a_seller_close(client):
    listing_id = await _persist(client)
    await client.update_listing(listing_id=listing_id, status="closed", closed_by="seller")

    await client.update_listing(
        listing_id=listing_id, status="closed", closed_by="reconciliation"
    )

    assert (await client.load_listing(listing_id=listing_id))["closed_by"] == "seller"


async def test_reopener_is_recorded_only_with_a_reopen(client):
    listing_id = await _persist(client)
    with pytest.raises(ValueError, match="reopened_by"):
        await client.update_listing(
            listing_id=listing_id,
            status="closed",
            closed_by="seller",
            reopened_by="seller",
        )
    with pytest.raises(ValueError, match="reopened_by"):
        await client.update_listing(
            listing_id=listing_id, status="open", reopened_by="operator"
        )


async def test_upsert_cannot_overwrite_a_seller_close(client):
    listing_id = await _persist(client)
    await client.update_listing(listing_id=listing_id, status="closed", closed_by="seller")

    with pytest.raises(SellerClosedListingError):
        await _persist(client, listing_id)

    row = await client.load_listing(listing_id=listing_id)
    assert (row["status"], row["closed_by"]) == ("closed", "seller")


async def test_connection_level_write_applies_the_same_guard(client):
    listing_id = await _persist(client)
    await client.update_listing(listing_id=listing_id, status="closed", closed_by="seller")

    conn = sqlite3.connect(client.db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(SellerClosedListingError):
            write_listing_update(conn, listing_id=listing_id, status="open")
        conn.rollback()
    finally:
        conn.close()
    assert (await client.load_listing(listing_id=listing_id))["status"] == "closed"
