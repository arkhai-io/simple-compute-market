"""Tests that publication_service records a ``publications`` row after each
fan-out write — publish_order_to_registry and close_order.

These wire the new ``MultiRegistryClient.publish_listing_per_registry``
(et al.) into the SQLite ``publications`` table introduced in PR (b2).
The fan-out client is mocked; the SQLite layer is real so the test
asserts on actual rows.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from market_storefront.services import publication_service
from market_storefront.utils.multi_registry_client import PublishResult
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides


def _mock_multi_registry(urls: list[str], results: list[PublishResult]):
    """Build a MultiRegistryClient mock that exposes ``urls`` and returns
    the given per-registry results from every write method."""
    client = MagicMock()
    client.urls = list(urls)
    client.publish_listing_per_registry = AsyncMock(return_value=results)
    client.update_listing_per_registry = AsyncMock(return_value=results)
    client.delete_listing_per_registry = AsyncMock(return_value=results)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm, client


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "pubs_wiring.db"))


@pytest.fixture
def patched_sqlite(db, monkeypatch):
    """Wire ``get_sqlite_client`` to return a fresh in-test DB so the
    publications rows can be asserted on after the action runs."""
    monkeypatch.setattr(publication_service, "get_sqlite_client", lambda: db)
    return db


class TestPublishOrderRecordsPublications:
    @pytest.mark.asyncio
    async def test_successful_fanout_writes_one_row_per_registry(
        self, patched_sqlite,
    ):
        order = {
            "listing_id": "L1",
            "offer_resource": {"gpu_model": "H200"},
            "accepted_escrows": [{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
            }],
            "max_duration_seconds": 3600,
        }
        results = [
            PublishResult(
                registry_url="http://r1", success=True,
                response={"listing_id": "r1-id"}, error=None,
                payload={"listing_id": "L1"}, registry_assigned_id="r1-id",
            ),
            PublishResult(
                registry_url="http://r2", success=True,
                response={"listing_id": "r2-id"}, error=None,
                payload={"listing_id": "L1"}, registry_assigned_id="r2-id",
            ),
        ]
        cm, _client = _mock_multi_registry(["http://r1", "http://r2"], results)
        with (
            patch("market_storefront.services.publication_service._make_registry_client",
                  return_value=cm),
            settings_overrides(enable_registry_discovery=True,
                               **{"wallet.private_key": "0xkey"}),
        ):
            out = await publication_service.publish_order_to_registry(order)
        assert out["status"] == "published"

        rows = await patched_sqlite.load_publications(listing_id="L1")
        assert {r["registry_url"] for r in rows} == {"http://r1", "http://r2"}
        for r in rows:
            assert r["status"] == "published"
            assert r["registry_assigned_id"] in {"r1-id", "r2-id"}

    @pytest.mark.asyncio
    async def test_partial_failure_records_both_statuses(self, patched_sqlite):
        """One registry fails, one succeeds — we want a 'failed' row for
        the bad one (with last_error) and a 'published' row for the good
        one. This is the audit trail consumers will read to retry."""
        order = {
            "listing_id": "Lpartial",
            "offer_resource": {"gpu_model": "H200"},
            "accepted_escrows": [{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
            }],
            "max_duration_seconds": 3600,
        }
        results = [
            PublishResult(
                registry_url="http://r1", success=False,
                response=None, error="connection refused",
                payload={"listing_id": "Lpartial"},
                registry_assigned_id=None,
            ),
            PublishResult(
                registry_url="http://r2", success=True,
                response={"listing_id": "r2-id"}, error=None,
                payload={"listing_id": "Lpartial"},
                registry_assigned_id="r2-id",
            ),
        ]
        cm, _ = _mock_multi_registry(["http://r1", "http://r2"], results)
        with (
            patch("market_storefront.services.publication_service._make_registry_client",
                  return_value=cm),
            settings_overrides(enable_registry_discovery=True,
                               **{"wallet.private_key": "0xkey"}),
        ):
            out = await publication_service.publish_order_to_registry(order)
        # At least one OK → overall status is 'published'.
        assert out["status"] == "published"

        rows = {
            r["registry_url"]: r
            for r in await patched_sqlite.load_publications(listing_id="Lpartial")
        }
        assert rows["http://r1"]["status"] == "failed"
        assert rows["http://r1"]["last_error"] == "connection refused"
        assert rows["http://r2"]["status"] == "published"


class TestRegistriesToTarget:
    """``_registries_to_target`` consults ``publications`` so updates and
    deletes only contact registries the listing was actually sent to."""

    @pytest.mark.asyncio
    async def test_returns_active_publications(self, patched_sqlite):
        await patched_sqlite.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={}, status="published",
        )
        await patched_sqlite.upsert_publication(
            listing_id="L1", registry_url="http://r2",
            payload={}, status="published",
        )
        urls = await publication_service._registries_to_target(
            "L1", ["http://r1", "http://r2", "http://r3"],
        )
        assert sorted(urls) == ["http://r1", "http://r2"]

    @pytest.mark.asyncio
    async def test_falls_back_to_all_urls_when_no_publications(
        self, patched_sqlite,
    ):
        urls = await publication_service._registries_to_target(
            "no-such-listing", ["http://r1", "http://r2"],
        )
        assert urls == ["http://r1", "http://r2"]

    @pytest.mark.asyncio
    async def test_skips_unpublished_rows(self, patched_sqlite):
        """A tombstoned (status='unpublished') row should not be targeted
        by subsequent updates — the listing is gone from that registry."""
        await patched_sqlite.upsert_publication(
            listing_id="L1", registry_url="http://r1",
            payload={}, status="published",
        )
        await patched_sqlite.upsert_publication(
            listing_id="L1", registry_url="http://r2",
            payload={}, status="unpublished",
        )
        urls = await publication_service._registries_to_target(
            "L1", ["http://r1", "http://r2"],
        )
        assert urls == ["http://r1"]
