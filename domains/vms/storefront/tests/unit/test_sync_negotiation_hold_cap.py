"""Unit tests for VM pool-policy resolution used by the shared runtime hook.

External boundary: a real SQLite storefront binding, plus a projection state
the test builds over fake sites and passes in, as composition passes the
storefront's one state.
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
from tests.fake_site import (
    TEST_MARKETPLACE_SIGNER,
    FakeProjectionSite,
    loaded_site_projection_state,
)

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
    listing_resource = {
        "gpu_model": "H200",
        "gpu_count": gpu_count,
        "offering_mode": "vm",
    }
    if pool_id is not None:
        listing_resource["pool_id"] = pool_id
    if resource_id is not None:
        listing_resource["resource_id"] = resource_id
    binding = prepare_vm_listing_binding(
        listing_id=listing_id,
        candidate={
            "capacity_backing": "backed",
            "site_id": site_id,
            "pool_id": pool_id,
            "resource_id": resource_id,
            "listing_shape": {"gpu": {"count": gpu_count, "model": "H200"}},
        },
    )
    repository = SQLiteClient(db_path=db_path, registry=_VM_REGISTRY)
    asyncio.run(
        repository.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at="2026-08-15T00:00:00Z",
            updated_at="2026-08-15T00:00:00Z",
            listing_resource=listing_resource,
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="http://storefront.test",
            seller_principal=TEST_MARKETPLACE_SIGNER.identity,
            accepted_escrows=[],
        )
    )


def _held(pools_by_site: dict):
    """A state holding what each site serves; a site serving ``None`` has never
    answered, so the state holds nothing for it."""
    return asyncio.run(
        loaded_site_projection_state(
            {
                site: FakeProjectionSite(resource_pools=pools)
                for site, pools in (pools_by_site or {"site-z": []}).items()
            }
        )
    )


class TestLookupPoolPolicyTags:
    def test_none_listing_id_returns_empty(self, db_path):
        state = _held({})
        assert lookup_pool_policy_tags(_Client(db_path), None, state) == {}

    def test_unmapped_listing_returns_empty(self, db_path):
        state = _held({})
        assert lookup_pool_policy_tags(_Client(db_path), "listing-none", state) == {}

    def test_resolves_policy_tags_for_mapped_pool(self, db_path):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        state = _held({
            "site-a": [
                {
                    "pool_id": "gpu-pool",
                    "resources": [],
                    "pool_metadata": {
                        "policy_tags": {
                            "deliverable_modes": ["vm"],
                            "max_reservation_hold_seconds": 30,
                        },
                    },
                },
            ],
        })
        tags = lookup_pool_policy_tags(_Client(db_path), "listing-1", state)
        assert tags == {
            "deliverable_modes": ["vm"],
            "max_reservation_hold_seconds": 30,
        }

    def test_empty_when_site_not_in_cache(self, db_path):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        state = _held({})  # site-a never loaded
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1", state) == {}

    def test_empty_when_cached_value_has_not_loaded_yet(self, db_path):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        state = _held({"site-a": None})
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1", state) == {}

    def test_empty_when_pool_absent_from_cached_projection(self, db_path):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        state = _held({
            "site-a": [
                {
                    "pool_id": "a-different-pool",
                    "resources": [],
                    "pool_metadata": {
                        "policy_tags": {"deliverable_modes": ["vm"]},
                    },
                },
            ],
        })
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1", state) == {}

    def test_empty_when_pool_has_no_metadata(self, db_path):
        _record_bound_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            pool_id="gpu-pool",
            resource_id=None,
            gpu_count=4,
        )
        state = _held({
            "site-a": [
                {"pool_id": "gpu-pool", "resources": []},
            ],
        })
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1", state) == {}

    def test_specific_resource_only_mapping_does_not_falsely_match_a_pool(
        self, db_path,
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
        state = _held({
            "site-a": [
                {
                    "pool_id": "gpu-pool",
                    "resources": [],
                    "pool_metadata": {
                        "policy_tags": {
                            "deliverable_modes": ["vm"],
                            "max_reservation_hold_seconds": 30,
                        },
                    },
                },
            ],
        })
        assert lookup_pool_policy_tags(_Client(db_path), "listing-1", state) == {}


class _Client:
    """Minimal stand-in for SQLiteClient -- lookup_pool_policy_tags only
    reads ``.db_path``."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
