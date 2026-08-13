"""Unit tests for market_storefront.utils.sync_negotiation.lookup_pool_policy_tags.

External boundary: a real sqlite file DB (derived_compute_listings), plus
a fake in-memory projection cache satisfying the same duck-typed shape
``site_projection_cache.projection_caches()`` produces -- patched at its
source module (this function imports it locally, at call time, so
patching the source is the correct seam here, not a module-level-import
anti-pattern; see docs/development/TESTING.md).
"""

from __future__ import annotations

import sqlite3

import pytest

from market_storefront.listings.reconciler import record_derived_listing
from market_storefront.utils.sync_negotiation import lookup_pool_policy_tags


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "hold_cap_test.db")
    sqlite3.connect(path).close()
    return path


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
        record_derived_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(
            monkeypatch,
            {
                "site-a": _FakeSiteCaches(
                    [
                        {
                            "resource_pool_id": "gpu-pool",
                            "resources": [],
                            "pool_metadata": {
                                "policy_tags": {"max_reservation_hold_seconds": 30},
                            },
                        },
                    ]
                ),
            },
        )
        tags = lookup_pool_policy_tags(_Client(db_path), "listing-1")
        assert tags == {"max_reservation_hold_seconds": 30}

    def test_empty_when_site_not_in_cache(self, db_path, monkeypatch):
        record_derived_listing(
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
        record_derived_listing(
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
        record_derived_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(
            monkeypatch,
            {
                "site-a": _FakeSiteCaches(
                    [
                        {"resource_pool_id": "a-different-pool", "resources": []},
                    ]
                ),
            },
        )
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}

    def test_empty_when_pool_has_no_metadata(self, db_path, monkeypatch):
        record_derived_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        _patch_caches(
            monkeypatch,
            {
                "site-a": _FakeSiteCaches(
                    [
                        {"resource_pool_id": "gpu-pool", "resources": []},
                    ]
                ),
            },
        )
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}

    def test_specific_resource_only_mapping_does_not_falsely_match_a_pool(
        self,
        db_path,
        monkeypatch,
    ):
        """A listing mapped only to a resource_id has its pool_id column
        backfilled to that resource_id (record_derived_listing's own
        fallback) -- looking that up against the cache's real pool ids
        should simply not match anything, not require special-casing."""
        record_derived_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id=None,
            resource_id="res-1",
            gpu_count=4,
        )
        _patch_caches(
            monkeypatch,
            {
                "site-a": _FakeSiteCaches(
                    [
                        {
                            "resource_pool_id": "gpu-pool",
                            "resources": [],
                            "pool_metadata": {
                                "policy_tags": {"max_reservation_hold_seconds": 30},
                            },
                        },
                    ]
                ),
            },
        )
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1") == {}


class _Client:
    """Minimal stand-in for SQLiteClient -- lookup_pool_policy_tags only
    reads ``.db_path``."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
