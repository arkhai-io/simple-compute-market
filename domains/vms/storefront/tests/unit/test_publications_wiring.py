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
from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionIdentity,
    ProjectionState,
)
from market_capacity_publication import BoundListing

from market_storefront.services import publication_service
from core_storefront.multi_registry_client import PublishResult
from market_storefront.utils.config import BASE_URL_OVERRIDE
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.services.listing_service import ListingService
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.services import site_projection_cache
from tests._settings_overrides import settings_overrides
from tests.listing_service_fixtures import vm_listing_collaborators
from tests.fake_site import TEST_SITE_AUTHORITIES

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
def vm_pool_projection():
    resource_pools = ProjectionCache(client=None)
    resource_pools._value = [{
        "resource_pool_id": "pool-vm",
        "pool_metadata": {
            "policy_tags": {"deliverable_modes": ["vm"]},
        },
        "resources": [],
    }]
    resource_pools._state = ProjectionState.loaded
    resource_pools._identity = ProjectionIdentity(revision=1, digest="vm-pool")
    caches = site_projection_cache.SiteProjectionCaches(
        resource_pools=resource_pools,
        capacity_buckets=ProjectionCache(client=None),
    )
    with patch.dict(
        site_projection_cache._caches,
        {"site-a": caches},
        clear=True,
    ):
        yield


@pytest.fixture
def db(tmp_path, vm_pool_projection):
    domain = build_vm_storefront_domain()
    registry = build_vm_storefront_registry(domain)
    return SQLiteClient(
        db_path=str(tmp_path / "pubs_wiring.db"),
        registry=registry,
    )


@pytest.fixture
def patched_sqlite(db):
    return db


async def _persist_bound_listing(db: SQLiteClient, order: dict) -> None:
    from domains.vms.listings.models import Listing

    listing = Listing.model_validate(order)
    wire = listing.model_dump(mode="json")
    binding = prepare_vm_listing_binding(
        listing_id=listing.listing_id,
        candidate={
            "site_id": "site-a",
            "pool_id": "pool-vm",
            "resource_id": listing.offer_resource.resource_id,
            "gpu_count": listing.offer_resource.gpu_count,
        },
    )
    await db.upsert_listing_with_binding(
        binding=binding,
        status="open",
        created_at="2026-08-11T00:00:00",
        updated_at="2026-08-11T00:00:00",
        offer_resource=wire["offer_resource"],
        fulfillment_resource=None,
        max_duration_seconds=listing.max_duration_seconds,
        storefront_url=listing.storefront_url,
        seller_principal=listing.seller_principal,
        oracle_address=listing.oracle_address,
        accepted_escrows=wire.get("accepted_escrows"),
        settlement_options=wire.get("settlement_options"),
        demands=wire.get("demands"),
    )


def _compute_order(listing_id: str) -> dict:
    return {
        "listing_id": listing_id,
        "storefront_url": BASE_URL_OVERRIDE,
        "seller_principal": _SELLER_PRINCIPAL,
        "offer_resource": {
            "resource_id": f"res-{listing_id}",
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "test",
            "virtualization_type": "vm",
        },
        "accepted_escrows": [{
            "chain_name": "anvil",
            "escrow_address": "0x" + "11" * 20,
            "literal_fields": {"token": "0x" + "22" * 20},
            "rates": [{"field": "amount", "per": "hour", "value": "1000"}],
        }],
        "max_duration_seconds": 3600,
    }


def test_listing_validation_uses_the_exact_injected_codec(tmp_path) -> None:
    domain = build_vm_storefront_domain()
    listing_codec = Mock(wraps=domain.codecs.normalize_listing)
    domain = replace(
        domain,
        codecs=replace(domain.codecs, normalize_listing=listing_codec),
    )
    registry = build_vm_storefront_registry(domain)
    collaborators = vm_listing_collaborators(
        registry,
        signer=_SELLER,
        authorities=TEST_SITE_AUTHORITIES,
    )
    db = SQLiteClient(
        db_path=str(tmp_path / "injected-codec.db"),
        registry=registry,
    )
    service = ListingService(
        registry=collaborators.registry,
        binding=collaborators.binding,
        domain=collaborators.domain,
        capacity_runtime=collaborators.capacity_runtime,
        sqlite_client=db,
        marketplace_signer=_SELLER,
        alkahest_clients={},
        settlement_composition_provider=lambda: object(),
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
                "virtualization_type": "vm",
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
    repository_registry = build_vm_storefront_registry(repository_domain)
    other_domain = build_vm_storefront_domain()
    other_registry = build_vm_storefront_registry(other_domain)
    other_collaborators = vm_listing_collaborators(
        other_registry,
        signer=_SELLER,
        authorities=TEST_SITE_AUTHORITIES,
    )
    persistence = Mock()
    repository = SimpleNamespace(
        domain_registry=repository_registry,
        market_domain=repository_domain,
        upsert_listing=persistence,
    )

    with pytest.raises(
        RuntimeError,
        match="share the exact storefront domain registry object",
    ):
        ListingService(
            registry=other_collaborators.registry,
            binding=other_collaborators.binding,
            domain=other_collaborators.domain,
            capacity_runtime=other_collaborators.capacity_runtime,
            sqlite_client=repository,
            marketplace_signer=_SELLER,
            alkahest_clients={},
            settlement_composition_provider=lambda: object(),
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
                "gpu_model": "H200",
                "gpu_count": 1,
                "sla": 99.9,
                "region": "test",
                "virtualization_type": "vm",
            },
            "accepted_escrows": [],
        }
        factory = Mock()
        with settings_overrides(
            enable_registry_discovery=True,
            registry__urls=["http://r1"],
        ):
            runtime = publication_service.build_publication_runtime(
                db,
                registry_client_factory=factory,
            )
            with pytest.raises(ValueError, match="pool_id or resource_id"):
                await runtime.publish(await publication_service._candidate(db, order))
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_mutated_listing_model_is_revalidated_before_publish(self, db):
        from domains.vms.listings.models import Listing

        listing = Listing.model_validate(_compute_order("mutated-listing"))
        listing.offer_resource.resource_id = None
        listing.offer_resource.pool_id = None
        factory = Mock()

        with settings_overrides(
            enable_registry_discovery=True,
            registry__urls=["http://r1"],
        ):
            runtime = publication_service.build_publication_runtime(
                db,
                registry_client_factory=factory,
            )
            with pytest.raises(ValueError, match="pool_id or resource_id"):
                await runtime.publish(await publication_service._candidate(db, listing))
        factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_fanout_writes_one_row_per_registry(
        self, patched_sqlite,
    ):
        order = _compute_order("L1")
        await _persist_bound_listing(patched_sqlite, order)
        results = [
            PublishResult(
                registry_url="http://r1",
                success=True,
                response=_registry_publish_response("L1"),
                error=None,
                payload={"listing_id": "L1"},
                registry_assigned_id="L1",
            ),
            PublishResult(
                registry_url="http://r2",
                success=True,
                response=_registry_publish_response("L1"),
                error=None,
                payload={"listing_id": "L1"},
                registry_assigned_id="L1",
            ),
        ]
        cm, client = _mock_multi_registry(["http://r1", "http://r2"], results)
        factory = Mock(return_value=cm)
        with (
            patch(
                "market_storefront.services.publication_service.stage_event",
            ) as stage_event,
            settings_overrides(
                enable_registry_discovery=True,
                registry__urls=["http://r1", "http://r2"],
            ),
        ):
            runtime = publication_service.build_publication_runtime(
                patched_sqlite,
                registry_client_factory=factory,
            )
            out = await runtime.publish(
                await publication_service._candidate(patched_sqlite, order)
            )

        assert out["status"] == "published"
        factory.assert_called_once_with()
        assert stage_event.call_args.kwargs["agent_url"] == BASE_URL_OVERRIDE
        assert stage_event.call_args.kwargs["seller_principal"] == (
            _SELLER_PRINCIPAL.model_dump(mode="json")
        )
        publish_kwargs = client.publish_listing_per_registry.await_args.kwargs
        assert set(publish_kwargs) == {"payloads"}
        assert set(publish_kwargs["payloads"]) == {"http://r1", "http://r2"}
        published_request = publish_kwargs["payloads"]["http://r1"]
        assert published_request.storefront_url == BASE_URL_OVERRIDE
        assert not hasattr(published_request, "private_key")

        rows = await patched_sqlite.load_publications(listing_id="L1")
        assert {r["registry_url"] for r in rows} == {"http://r1", "http://r2"}
        for row in rows:
            assert row["status"] == "published"
            assert row["registry_assigned_id"] == "L1"

    @pytest.mark.asyncio
    async def test_injected_client_must_match_exact_configured_fanout(
        self, patched_sqlite,
    ):
        order = _compute_order("Lfanout-mismatch")
        await _persist_bound_listing(patched_sqlite, order)
        cm, client = _mock_multi_registry(["http://r1", "http://r3"], [])
        with settings_overrides(
            enable_registry_discovery=True,
            registry__urls=["http://r1", "http://r2"],
        ):
            runtime = publication_service.build_publication_runtime(
                patched_sqlite,
                registry_client_factory=Mock(return_value=cm),
            )
            result = await runtime.publish(
                await publication_service._candidate(patched_sqlite, order)
            )

        assert result["status"] == "error"
        assert "exact configured fanout" in result["message"]
        client.publish_listing_per_registry.assert_not_awaited()
        assert await patched_sqlite.load_publications(
            listing_id="Lfanout-mismatch"
        ) == []

    @pytest.mark.asyncio
    async def test_partial_failure_records_both_statuses(self, patched_sqlite):
        order = _compute_order("Lpartial")
        await _persist_bound_listing(patched_sqlite, order)
        results = [
            PublishResult(
                registry_url="http://r1",
                success=False,
                response=None,
                error="connection refused",
                payload={"listing_id": "Lpartial"},
                registry_assigned_id=None,
            ),
            PublishResult(
                registry_url="http://r2",
                success=True,
                response=_registry_publish_response("Lpartial"),
                error=None,
                payload={"listing_id": "Lpartial"},
                registry_assigned_id="Lpartial",
            ),
        ]
        cm, _client = _mock_multi_registry(["http://r1", "http://r2"], results)
        factory = Mock(return_value=cm)
        with settings_overrides(
            enable_registry_discovery=True,
            registry__urls=["http://r1", "http://r2"],
        ):
            runtime = publication_service.build_publication_runtime(
                patched_sqlite,
                registry_client_factory=factory,
            )
            out = await runtime.publish(
                await publication_service._candidate(patched_sqlite, order)
            )

        assert out["status"] == "published"
        rows = {
            row["registry_url"]: row
            for row in await patched_sqlite.load_publications(
                listing_id="Lpartial"
            )
        }
        assert rows["http://r1"]["status"] == "failed"
        assert rows["http://r1"]["last_error"] == "connection refused"
        assert rows["http://r2"]["status"] == "published"



class TestRegistryTargets:
    @pytest.mark.asyncio
    async def test_close_consumes_only_active_persisted_targets(
        self, patched_sqlite,
    ):
        order = _compute_order("Ltargets")
        await _persist_bound_listing(patched_sqlite, order)
        await patched_sqlite.upsert_publication(
            listing_id="Ltargets",
            registry_url="http://r1",
            payload={},
            status="published",
            registry_assigned_id="Ltargets",
        )
        await patched_sqlite.upsert_publication(
            listing_id="Ltargets",
            registry_url="http://r2",
            payload={},
            status="unpublished",
            registry_assigned_id="Ltargets",
        )
        await patched_sqlite.upsert_publication(
            listing_id="Ltargets",
            registry_url="http://r3",
            payload={},
            status="failed",
            registry_assigned_id="Ltargets",
            last_error="prior timeout",
        )
        results = [
            PublishResult(
                registry_url=url,
                success=True,
                response={"listing_id": "Ltargets", "status": "closed"},
                error=None,
                payload={"updates": {"status": "closed"}},
                registry_assigned_id="Ltargets",
            )
            for url in ("http://r1", "http://r3")
        ]
        cm, client = _mock_multi_registry(
            ["http://r1", "http://r2", "http://r3"],
            results,
        )
        with settings_overrides(
            enable_registry_discovery=True,
            registry__urls=["http://r1", "http://r2", "http://r3"],
        ):
            runtime = publication_service.build_publication_runtime(
                patched_sqlite,
                registry_client_factory=Mock(return_value=cm),
            )
            candidate = await publication_service._candidate(
                patched_sqlite,
                order,
            )
            result = await runtime.close(
                BoundListing(candidate.listing_id, candidate.binding)
            )

        assert result["status"] == "closed"
        update_kwargs = client.update_listing_per_registry.await_args.kwargs
        assert set(update_kwargs["payloads"]) == {"http://r1", "http://r3"}
        rows = {
            row["registry_url"]: row
            for row in await patched_sqlite.load_publications(
                listing_id="Ltargets"
            )
        }
        assert {url: row["status"] for url, row in rows.items()} == {
            "http://r1": "unpublished",
            "http://r2": "unpublished",
            "http://r3": "unpublished",
        }

    @pytest.mark.asyncio
    async def test_close_without_history_targets_every_configured_registry(
        self, patched_sqlite,
    ):
        order = _compute_order("Lfallback")
        await _persist_bound_listing(patched_sqlite, order)
        results = [
            PublishResult(
                registry_url=url,
                success=True,
                response={"listing_id": "Lfallback", "status": "closed"},
                error=None,
                payload={"updates": {"status": "closed"}},
                registry_assigned_id="Lfallback",
            )
            for url in ("http://r1", "http://r2")
        ]
        cm, client = _mock_multi_registry(["http://r1", "http://r2"], results)
        with settings_overrides(
            enable_registry_discovery=True,
            registry__urls=["http://r1", "http://r2"],
        ):
            runtime = publication_service.build_publication_runtime(
                patched_sqlite,
                registry_client_factory=Mock(return_value=cm),
            )
            candidate = await publication_service._candidate(
                patched_sqlite,
                order,
            )
            result = await runtime.close(
                BoundListing(candidate.listing_id, candidate.binding)
            )

        assert result["status"] == "closed"
        update_kwargs = client.update_listing_per_registry.await_args.kwargs
        assert set(update_kwargs["payloads"]) == {"http://r1", "http://r2"}
