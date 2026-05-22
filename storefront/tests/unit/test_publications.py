"""Tests for the ``publications`` table CRUD on :class:`SQLiteClient`.

The table records which registry received which payload for a listing,
so updates and deletes can target the right subset of registries when
fan-out diverges per-registry (milestone b2 of the generic-escrow plan).
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def client(tmp_path):
    from market_storefront.utils.sqlite_client import SQLiteClient
    return SQLiteClient(db_path=str(tmp_path / "pubs.db"))


class TestUpsertPublication:
    """``upsert_publication`` is the single write entry point."""

    @pytest.mark.asyncio
    async def test_insert_creates_row(self, client):
        await client.upsert_publication(
            listing_id="L1",
            registry_url="http://r1",
            payload={"listing_id": "L1", "offer": {"gpu_model": "H200"}},
            status="published",
            registry_assigned_id="r1-listing-id",
        )
        row = await client.load_publication(
            listing_id="L1", registry_url="http://r1",
        )
        assert row is not None
        assert row["status"] == "published"
        assert row["registry_assigned_id"] == "r1-listing-id"
        assert row["payload"] == {"listing_id": "L1", "offer": {"gpu_model": "H200"}}
        # published_at is auto-filled when not supplied
        assert isinstance(row["published_at"], int) and row["published_at"] > 0

    @pytest.mark.asyncio
    async def test_upsert_replaces_existing_row(self, client):
        """Second insert with same (listing_id, registry_url) overwrites
        the first — registries that re-publish should see the latest
        payload, not a duplicate row."""
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={"v": 1}, status="published",
        )
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={"v": 2}, status="failed", last_error="boom",
        )
        rows = await client.load_publications(listing_id="L1")
        assert len(rows) == 1
        assert rows[0]["payload"] == {"v": 2}
        assert rows[0]["status"] == "failed"
        assert rows[0]["last_error"] == "boom"

    @pytest.mark.asyncio
    async def test_string_payload_roundtrips_as_dict(self, client):
        """Callers may pass a pre-serialised payload string; load returns
        the parsed dict so the caller doesn't have to re-decode."""
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload=json.dumps({"already": "serialised"}),
            status="published",
        )
        row = await client.load_publication(
            listing_id="L1", registry_url="http://r1",
        )
        assert row["payload"] == {"already": "serialised"}

    @pytest.mark.asyncio
    async def test_explicit_published_at_is_respected(self, client):
        """Tests pinning a deterministic timestamp need this — without
        it ``int(time.time())`` makes timestamp assertions flaky."""
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={}, status="published",
            published_at=1_700_000_000,
        )
        row = await client.load_publication(
            listing_id="L1", registry_url="http://r1",
        )
        assert row["published_at"] == 1_700_000_000


class TestLoadPublications:
    @pytest.mark.asyncio
    async def test_returns_all_registries_for_one_listing(self, client):
        for url in ("http://r1", "http://r2", "http://r3"):
            await client.upsert_publication(
                listing_id="L1", registry_url=url,
                payload={"v": url}, status="published",
            )
        rows = await client.load_publications(listing_id="L1")
        assert [r["registry_url"] for r in rows] == [
            "http://r1", "http://r2", "http://r3",
        ]

    @pytest.mark.asyncio
    async def test_empty_when_listing_unknown(self, client):
        rows = await client.load_publications(listing_id="missing")
        assert rows == []


class TestListPublications:
    """``list_publications`` supports operational queries — find every
    failed publish, every listing that went to a specific registry, etc."""

    @pytest.mark.asyncio
    async def test_filter_by_registry(self, client):
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={}, status="published",
        )
        await client.upsert_publication(
            listing_id="L2", registry_url="http://r1",
            payload={}, status="published",
        )
        await client.upsert_publication(
            listing_id="L3", registry_url="http://r2",
            payload={}, status="published",
        )
        on_r1 = await client.list_publications(registry_url="http://r1")
        assert sorted(r["listing_id"] for r in on_r1) == ["L1", "L2"]

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client):
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={}, status="published",
        )
        await client.upsert_publication(
            listing_id="L2", registry_url="http://r1",
            payload={}, status="failed", last_error="boom",
        )
        await client.upsert_publication(
            listing_id="L3", registry_url="http://r1",
            payload={}, status="unpublished",
        )
        failed = await client.list_publications(status="failed")
        assert [r["listing_id"] for r in failed] == ["L2"]

    @pytest.mark.asyncio
    async def test_combined_filter(self, client):
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={}, status="published",
        )
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r2",
            payload={}, status="failed",
        )
        result = await client.list_publications(
            registry_url="http://r1", status="published",
        )
        assert len(result) == 1
        assert result[0]["registry_url"] == "http://r1"


class TestDeletePublication:
    @pytest.mark.asyncio
    async def test_deletes_one_row(self, client):
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={}, status="published",
        )
        await client.upsert_publication(
            listing_id="L1", registry_url="http://r2",
            payload={}, status="published",
        )
        await client.delete_publication(
            listing_id="L1", registry_url="http://r1",
        )
        rows = await client.load_publications(listing_id="L1")
        assert [r["registry_url"] for r in rows] == ["http://r2"]

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, client):
        # Deleting a non-existent row is silent (idempotent).
        await client.delete_publication(
            listing_id="missing", registry_url="http://nowhere",
        )
