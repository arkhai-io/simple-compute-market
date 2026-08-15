"""Unit tests for VM pool-policy resolution used by the shared runtime hook.

External boundary: a real SQLite storefront binding, plus a fake in-memory
projection cache satisfying the same duck-typed shape
``site_projection_cache.projection_caches()`` produces -- patched at its
source module (this function imports it locally, at call time, so
patching the source is the correct seam here, not a module-level-import
anti-pattern; see docs/development/TESTING.md).
"""

from __future__ import annotations

import asyncio

import pytest

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.negotiation_runtime import lookup_pool_policy_tags
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.utils.sqlite_client import SQLiteClient
from tests.fake_site import TEST_MARKETPLACE_SIGNER

_VM_REGISTRY = build_vm_storefront_registry(build_vm_storefront_domain())


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "hold_cap_test.db")
    SQLiteClient(db_path=path, registry=_VM_REGISTRY)
    return path


def _record_bound_listing(
    db_path: str,
    *,
    listing_id: str,
    site_id: str,
    pool_id: str | None,
    resource_id: str | None,
    gpu_count: int,
) -> None:
    offer = {
        "gpu_model": "H200",
        "gpu_count": gpu_count,
        "virtualization_type": "vm",
    }
    if pool_id is not None:
        offer["pool_id"] = pool_id
    if resource_id is not None:
        offer["resource_id"] = resource_id
    binding = prepare_vm_listing_binding(
        listing_id=listing_id,
        candidate={
            "site_id": site_id,
            "pool_id": pool_id,
            "resource_id": resource_id,
            "gpu_count": gpu_count,
        },
    )
    repository = SQLiteClient(db_path=db_path, registry=_VM_REGISTRY)
    asyncio.run(
        repository.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at="2026-08-15T00:00:00Z",
            updated_at="2026-08-15T00:00:00Z",
            offer_resource=offer,
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="http://storefront.test",
            seller_principal=TEST_MARKETPLACE_SIGNER.identity,
            accepted_escrows=[],
        )
    )


class _FakeView:
    def __init__(self, value):
        self.value = value


class _FakeProjectionCache:
    def __init__(self, value):
        self._value = value

    def view(self):
        return _FakeView(self._value)


class _FakeSiteCaches:
    def __init__(self, resource_pools_value):
        self.resource_pools = _FakeProjectionCache(resource_pools_value)


def _patch_caches(monkeypatch, caches: dict):
    import market_storefront.services.site_projection_cache as cache_module

    monkeypatch.setattr(cache_module, "projection_caches", lambda: caches)


class TestLookupPoolPolicyTags:
    def test_none_listing_id_returns_empty(self, db_path, monkeypatch):
        _patch_caches(monkeypatch, {})
        assert lookup_pool_policy_tags(_Client(db_path), None) == {}

    def test_unmapped_listing_returns_empty(self, db_path, monkeypatch):
        _patch_caches(monkeypatch, {})
        assert lookup_pool_policy_tags(_Client(db_path), "listing-none") == {}

    def test_resolves_policy_tags_for_mapped_pool(self, db_path, monkeypatch):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(monkeypatch, {
            "site-a": _FakeSiteCaches([
                {
                    "resource_pool_id": "gpu-pool",
                    "resources": [],
                    "pool_metadata": {
                        "policy_tags": {
                            "deliverable_modes": ["vm"],
                            "max_reservation_hold_seconds": 30,
                        },
                    },
                },
            ]),
        })
        tags = lookup_pool_policy_tags(_Client(db_path), "listing-1")
        assert tags == {
            "deliverable_modes": ["vm"],
            "max_reservation_hold_seconds": 30,
        }

    def test_empty_when_site_not_in_cache(self, db_path, monkeypatch):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(monkeypatch, {})  # site-a never loaded
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}

    def test_empty_when_cached_value_has_not_loaded_yet(self, db_path, monkeypatch):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(monkeypatch, {"site-a": _FakeSiteCaches(None)})
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}

    def test_empty_when_pool_absent_from_cached_projection(self, db_path, monkeypatch):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(monkeypatch, {
            "site-a": _FakeSiteCaches([
                {
                    "resource_pool_id": "a-different-pool",
                    "resources": [],
                    "pool_metadata": {
                        "policy_tags": {"deliverable_modes": ["vm"]},
                    },
                },
            ]),
        })
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}

    def test_empty_when_pool_has_no_metadata(self, db_path, monkeypatch):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(monkeypatch, {
            "site-a": _FakeSiteCaches([
                {"resource_pool_id": "gpu-pool", "resources": []},
            ]),
        })
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}

    def test_specific_resource_only_mapping_does_not_falsely_match_a_pool(
        self, db_path, monkeypatch,
    ):
        """A resource-only durable binding has no pool_id, so a policy lookup
        must not accidentally treat the physical resource ID as a pool ID."""
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id=None,
            resource_id="res-1",
            gpu_count=4,
        )
        _patch_caches(monkeypatch, {
            "site-a": _FakeSiteCaches([
                {
                    "resource_pool_id": "gpu-pool",
                    "resources": [],
                    "pool_metadata": {
                        "policy_tags": {
                            "deliverable_modes": ["vm"],
                            "max_reservation_hold_seconds": 30,
                        },
                    },
                },
            ]),
        })
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}


class _Client:
    """Minimal stand-in for SQLiteClient -- lookup_pool_policy_tags only
    reads ``.db_path``."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
