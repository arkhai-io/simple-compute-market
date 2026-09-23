"""The guard's source check reads only the listing's own site."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionIdentity,
    ProjectionState,
)
from market_capacity_publication import CapacityBinding, UnbackedBinding
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.services import site_projection_cache
from market_storefront.services.listing_source_check import check_listing_source
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides

pytestmark = pytest.mark.asyncio

_TAGS = {"deliverable_modes": ["vm"], "advertisable_modes": ["vm"], "capacity_backing": "backed"}


def _pool(pool_id, *, gpu_model="H100", members=(("r1", 4, 4),), tags=_TAGS):
    return {
        "resource_pool_id": pool_id,
        "pool_metadata": {
            "enabled": True,
            "policy_tags": {**tags, "listing_cardinality_mode": "fungible", "region": "us-east"},
        },
        "resources": [
            {
                "physical_resource_id": f"{pool_id}-{rid}",
                "enabled": True,
                "capacity": {"gpu_count": count},
                "available": {"gpu_count": available},
                "attributes": {"gpu_model": gpu_model},
            }
            for rid, count, available in members
        ],
    }


def _caches(pools):
    cache = ProjectionCache(client=None)
    cache._value = pools
    cache._state = ProjectionState.loaded
    cache._identity = ProjectionIdentity(revision=1, digest="check")
    return site_projection_cache.SiteProjectionCaches(
        resource_pools=cache, capacity_buckets=ProjectionCache(client=None)
    )


class _Capacity:
    """Records which sites were asked for a snapshot."""

    def __init__(self, rows_by_site):
        self.rows_by_site = rows_by_site
        self.asked: list[str] = []

    def site_client(self, site_id):
        capacity = self

        class _Client:
            async def snapshot(self):
                capacity.asked.append(site_id)
                return capacity.rows_by_site.get(site_id, [])

        return _Client()


@pytest.fixture
def repository(tmp_path):
    return SQLiteClient(
        db_path=str(tmp_path / "check.db"),
        registry=build_vm_storefront_registry(build_vm_storefront_domain()),
    )


def _listing(pool_id="pool-a", gpu_count=2, gpu_model="H100"):
    return {
        "listing_resource": {
            "offering_mode": "vm",
            "pool_id": pool_id,
            "gpu_model": gpu_model,
            "gpu_count": gpu_count,
            "region": "us-east",
        }
    }


async def _check(repository, projections, binding, listing, capacity):
    with settings_overrides(**{"capacity.use_site_projection_for_listings": True}), patch.dict(
        site_projection_cache._caches,
        {site: _caches(pools) for site, pools in projections.items()},
        clear=True,
    ):
        return await check_listing_source(
            repository=repository,
            listing_record=listing,
            binding=binding,
            capacity_runtime=capacity,
        )


async def test_availability_is_read_from_the_pinned_site_only(repository):
    capacity = _Capacity(
        {
            "site-a": [{"resource_id": "pool-a-r1", "available_units": 4}],
            "site-b": [{"resource_id": "pool-a-r1", "available_units": 4}],
        }
    )
    result = await _check(
        repository,
        {"site-a": [_pool("pool-a")], "site-b": [_pool("pool-a")]},
        CapacityBinding("site-a", "vm", "pool-a"),
        _listing(),
        capacity,
    )

    assert result["declared_match"] is True
    assert result["available"] is True
    assert capacity.asked == ["site-a"]


async def test_a_match_only_at_another_site_is_not_a_match(repository):
    capacity = _Capacity({})
    result = await _check(
        repository,
        {"site-a": [_pool("pool-a", gpu_model="A100")], "site-b": [_pool("pool-a")]},
        CapacityBinding("site-a", "vm", "pool-a"),
        _listing(),
        capacity,
    )

    assert result["declared_match"] is False
    assert "gpu_model" in result["differing_fields"]
    assert capacity.asked == []


async def test_a_match_only_in_another_pool_is_not_a_match(repository):
    result = await _check(
        repository,
        {"site-a": [_pool("pool-b")]},
        CapacityBinding("site-a", "vm", "pool-a"),
        _listing(),
        _Capacity({}),
    )

    assert result["declared_match"] is False


async def test_a_fungible_match_needs_one_member_large_enough(repository):
    pool = _pool("pool-a", members=(("r1", 2, 2), ("r2", 2, 2)))

    too_large = await _check(
        repository, {"site-a": [pool]},
        CapacityBinding("site-a", "vm", "pool-a"), _listing(gpu_count=4), _Capacity({}),
    )
    fits = await _check(
        repository, {"site-a": [pool]},
        CapacityBinding("site-a", "vm", "pool-a"), _listing(gpu_count=2), _Capacity({}),
    )

    assert too_large["declared_match"] is False
    assert fits["declared_match"] is True


async def test_an_unbacked_listing_makes_no_site_call(repository):
    tags = {"deliverable_modes": [], "advertisable_modes": ["vm"], "capacity_backing": "unbacked"}
    capacity = _Capacity({})

    result = await _check(
        repository,
        {"site-a": [_pool("pool-a", tags=tags, members=(("r1", 4, 0),))]},
        UnbackedBinding("site-a", "vm", "pool-a"),
        _listing(),
        capacity,
    )

    assert result == {"declared_match": True, "differing_fields": [], "available": None}
    assert capacity.asked == []


async def test_a_backed_listing_with_nothing_free_is_declared_but_unavailable(repository):
    result = await _check(
        repository,
        {"site-a": [_pool("pool-a", members=(("r1", 4, 0),))]},
        CapacityBinding("site-a", "vm", "pool-a"),
        _listing(),
        _Capacity({"site-a": [{"resource_id": "pool-a-r1", "available_units": 0}]}),
    )

    assert result["declared_match"] is True
    assert result["available"] is False


async def test_an_unloaded_site_projection_confirms_nothing(repository):
    capacity = _Capacity({})

    result = await _check(
        repository,
        {"site-b": [_pool("pool-a")]},
        CapacityBinding("site-a", "vm", "pool-a"),
        _listing(),
        capacity,
    )

    assert result["declared_match"] is False
    assert result["differing_fields"] == ["source_unavailable"]
    assert capacity.asked == []
