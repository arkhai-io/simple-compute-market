"""Tests that publication_service records a ``publications`` row after each
fan-out write — publish_order_to_registry and close_order.

These wire the new ``MultiRegistryClient.publish_listing_per_registry``
(et al.) into the SQLite ``publications`` table introduced in PR (b2).
The fan-out client is mocked; the SQLite layer is real so the test
asserts on actual rows.
"""
from __future__ import annotations
from dataclasses import replace
from types import SimpleNamespace

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from market_identity import Ed25519Signer
from core_storefront.models.listing_models import CreateListingRequest

from market_storefront.services import publication_service
from core_storefront.multi_registry_client import PublishResult
from market_storefront.utils.config import BASE_URL_OVERRIDE
from market_storefront.domain_runtime import build_vm_storefront_domain
from market_storefront.services.listing_service import ListingService
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides

_SELLER = Ed25519Signer(b"\x73" * 32)
_SELLER_PRINCIPAL = _SELLER.identity

def _registry_publish_response(listing_id: str) -> dict:
    """Body returned after the registry client verifies a signed response."""
    return {
        "listing_id": listing_id,
        "publisher_id": 1,
        "publisher_principals": {
            "identities": [_SELLER_PRINCIPAL.model_dump(mode="json")],
        },
        "status": "open",
        "created_at": "2026-08-11T00:00:00",
        "updated_at": "2026-08-11T00:00:00",
    }


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
    return SQLiteClient(db_path=str(tmp_path / "pubs_wiring.db"), domain=build_vm_storefront_domain())


@pytest.fixture
def patched_sqlite(db):
    return db


def test_listing_validation_uses_the_exact_injected_codec(tmp_path) -> None:
    domain = build_vm_storefront_domain()
    listing_codec = Mock(wraps=domain.codecs.normalize_listing)
    domain = replace(
        domain,
        codecs=replace(domain.codecs, normalize_listing=listing_codec),
    )
    db = SQLiteClient(
        db_path=str(tmp_path / "injected-codec.db"),
        domain=domain,
    )
    service = ListingService(
        domain=domain,
        sqlite_client=db,
        marketplace_signer=_SELLER,
    )

    service._parse_offer_and_escrows(
        CreateListingRequest(
            offer={
                "resource_type": "compute",
                "resource_id": "resource-1",
                "gpu_model": "H200",
                "gpu_count": 1,
                "region": "test",
                "sla": 99.0,
            },
            accepted_escrows=[
                {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "11" * 20,
                    "literal_fields": {"token": "0x" + "22" * 20},
                    "rates": [
                        {"field": "amount", "per": "hour", "value": "1000"}
                    ],
                }
            ],
        )
    )

    listing_codec.assert_called_once()


def test_listing_composition_mismatch_fails_before_side_effects() -> None:
    repository_domain = build_vm_storefront_domain()
    other_domain = build_vm_storefront_domain()
    persistence = Mock()
    repository = SimpleNamespace(
        market_domain=repository_domain,
        upsert_listing=persistence,
    )

    with pytest.raises(RuntimeError, match="exact market-domain contract object"):
        ListingService(
            domain=other_domain,
            sqlite_client=repository,
            marketplace_signer=_SELLER,
        )

    persistence.assert_not_called()


class TestPublishOrderRecordsPublications:
    @pytest.mark.asyncio
    async def test_invalid_legacy_row_is_rejected_before_registry_contact(self, db):
        order = {
            "listing_id": "legacy-invalid",
            "storefront_url": BASE_URL_OVERRIDE,
            "seller_principal": _SELLER_PRINCIPAL,
            "offer_resource": {
                "gpu_model": "H200", "gpu_count": 1,
                "sla": 99.9, "region": "test",
            },
            "accepted_escrows": [],
        }
        with patch(
            "market_storefront.services.publication_service.publish_listing_to_registries",
            new_callable=AsyncMock,
        ) as publish:
            with pytest.raises(ValueError, match="pool_id or resource_id"):
                await publication_service.publish_order_to_registry(
                    order,
                    sqlite_client=db,
                )
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mutated_listing_model_is_revalidated_before_publish(self, db):
        from domains.vms.listings.models import Listing

        listing = Listing.model_validate({
            "listing_id": "mutated-listing",
            "storefront_url": BASE_URL_OVERRIDE,
            "seller_principal": _SELLER_PRINCIPAL,
            "offer_resource": {
                "resource_id": "res-before-mutation", "gpu_model": "H200",
                "gpu_count": 1, "sla": 99.9, "region": "test",
            },
            "accepted_escrows": [],
        })
        listing.offer_resource.resource_id = None
        listing.offer_resource.pool_id = None

        with patch(
            "market_storefront.services.publication_service.publish_listing_to_registries",
            new_callable=AsyncMock,
        ) as publish:
            with pytest.raises(ValueError, match="pool_id or resource_id"):
                await publication_service.publish_order_to_registry(
                    listing,
                    sqlite_client=db,
                )
        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_successful_fanout_writes_one_row_per_registry(
        self, patched_sqlite,
    ):
        order = {
            "listing_id": "L1",
            "storefront_url": BASE_URL_OVERRIDE,
            "seller_principal": _SELLER_PRINCIPAL,
            "offer_resource": {
                "resource_id": "res-L1", "gpu_model": "H200",
                "gpu_count": 1, "sla": 99.9, "region": "test",
            },
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
                response=_registry_publish_response("L1"), error=None,
                payload={"listing_id": "L1"}, registry_assigned_id="L1",
            ),
            PublishResult(
                registry_url="http://r2", success=True,
                response=_registry_publish_response("L1"), error=None,
                payload={"listing_id": "L1"}, registry_assigned_id="L1",
            ),
        ]
        cm, _client = _mock_multi_registry(["http://r1", "http://r2"], results)
        with (
            patch(
                "market_storefront.services.publication_service._make_registry_client",
                return_value=cm,
            ),
            patch(
                "market_storefront.services.publication_service.stage_event",
            ) as stage_event,
            settings_overrides(enable_registry_discovery=True),
        ):
            out = await publication_service.publish_order_to_registry(
                order,
                sqlite_client=patched_sqlite,
            )
        assert out["status"] == "published"
        assert stage_event.call_args.kwargs["agent_url"] == BASE_URL_OVERRIDE
        assert stage_event.call_args.kwargs["seller_principal"] == (
            _SELLER_PRINCIPAL.model_dump(mode="json")
        )
        publish_kwargs = _client.publish_listing_per_registry.await_args.kwargs
        assert set(publish_kwargs) == {"payloads"}
        published_request = publish_kwargs["payloads"]["http://r1"]
        assert published_request.storefront_url == BASE_URL_OVERRIDE
        assert not hasattr(published_request, "private_key")

        rows = await patched_sqlite.load_publications(listing_id="L1")
        assert {r["registry_url"] for r in rows} == {"http://r1", "http://r2"}
        for r in rows:
            assert r["status"] == "published"
            assert r["registry_assigned_id"] == "L1"

    @pytest.mark.asyncio
    async def test_partial_failure_records_both_statuses(self, patched_sqlite):
        """One registry fails, one succeeds — we want a 'failed' row for
        the bad one (with last_error) and a 'published' row for the good
        one. This is the audit trail consumers will read to retry."""
        order = {
            "listing_id": "Lpartial",
            "storefront_url": BASE_URL_OVERRIDE,
            "seller_principal": _SELLER_PRINCIPAL,
            "offer_resource": {
                "resource_id": "res-Lpartial", "gpu_model": "H200",
                "gpu_count": 1, "sla": 99.9, "region": "test",
            },
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
                response=_registry_publish_response("Lpartial"), error=None,
                payload={"listing_id": "Lpartial"},
                registry_assigned_id="Lpartial",
            ),
        ]
        cm, _ = _mock_multi_registry(["http://r1", "http://r2"], results)
        with (
            patch(
                "market_storefront.services.publication_service._make_registry_client",
                return_value=cm,
            ),
            settings_overrides(enable_registry_discovery=True),
        ):
            out = await publication_service.publish_order_to_registry(
                order,
                sqlite_client=patched_sqlite,
            )
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
            sqlite_client=patched_sqlite,
        )
        assert sorted(urls) == ["http://r1", "http://r2"]

    @pytest.mark.asyncio
    async def test_falls_back_to_all_urls_when_no_publications(
        self, patched_sqlite,
    ):
        urls = await publication_service._registries_to_target(
            "no-such-listing", ["http://r1", "http://r2"],
            sqlite_client=patched_sqlite,
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
            sqlite_client=patched_sqlite,
        )
        assert urls == ["http://r1"]
