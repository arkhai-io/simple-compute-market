"""The guard's source check reads only the listing's own site."""

from __future__ import annotations

from datetime import timedelta

import pytest

from market_capacity_publication import CAPACITY_BUCKET, RESOURCE_POOL, PublicationBinding
from market_resource_pools_contracts.backing import BACKED, UNBACKED
from market_policy.listing_source import ListingSourceVerdict
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from market_storefront.publication_binding import prepare_vm_listing_binding
from market_storefront.services.listing_source_check import check_listing_source
from market_storefront.utils.config import source_confirmation_seconds
from market_storefront.utils.sqlite_client import SQLiteClient
from tests._settings_overrides import settings_overrides
from tests.fake_site import (
    TEST_MARKETPLACE_SIGNER,
    FakeProjectionSite,
    loaded_site_projection_state,
)

pytestmark = pytest.mark.asyncio

_TAGS = {"deliverable_modes": ["vm"], "advertisable_modes": ["vm"], "capacity_backing": "backed"}


def _pool(pool_id, *, gpu_model="H100", members=(("r1", 4, 4),), tags=_TAGS):
    return {
        "pool_id": pool_id,
        "pool_metadata": {
            "enabled": True,
            "policy_tags": {**tags, "listing_cardinality_mode": "fungible", "region": "us-east"},
        },
        "resources": [
            {
                "physical_resource_id": f"{pool_id}-{rid}", "resource_type": "compute.gpu",
                "enabled": True,
                "capacity": {"gpu_count": count},
                "available": {"gpu_count": available},
                # A claim matches region against the declaration itself.
                "attributes": {"gpu_model": gpu_model, "region": "us-east"},
            }
            for rid, count, available in members
        ],
    }


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
        "listing_id": f"{pool_id}-{gpu_model}-{gpu_count}",
        "listing_resource": {
            "offering_mode": "vm",
            "pool_id": pool_id,
            "gpu_model": gpu_model,
            "gpu_count": gpu_count,
            "region": "us-east",
        }
    }


async def _bind(repository, binding, listing):
    """Store the listing's binding as publication does; the guard reads its key there."""
    resource = listing["listing_resource"]
    backing = binding.backing.label
    await repository.upsert_listing_with_binding(
        binding=prepare_vm_listing_binding(
            listing_id=listing["listing_id"],
            candidate={
                "site_id": binding.site_id,
                "pool_id": resource["pool_id"],
                "capacity_backing": backing,
                "listing_shape": {
                    "gpu": {"count": resource["gpu_count"], "model": resource["gpu_model"]}
                },
            },
        ),
        status="open",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        listing_resource=dict(resource, capacity_backing=backing, sla=99.0),
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller",
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
    )


async def _check(repository, projections, binding, listing, capacity):
    if await repository.load_listing_binding(listing_id=listing["listing_id"]) is None:
        await _bind(repository, binding, listing)
    # Each site serves its pools and no capacity buckets, so the check derives
    # fungible availability from the pool rows.
    state = await loaded_site_projection_state(
        {site: FakeProjectionSite(resource_pools=pools) for site, pools in projections.items()}
    )
    return await check_listing_source(
        repository=repository,
        listing_record=listing,
        binding=binding,
        capacity_runtime=capacity,
        site_projections=state,
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
        PublicationBinding("site-a", "vm", "pool-a", BACKED),
        _listing(),
        capacity,
    )

    assert result == ListingSourceVerdict("matches")
    assert capacity.asked == ["site-a"]


async def test_a_match_only_at_another_site_is_not_a_match(repository):
    capacity = _Capacity({})
    result = await _check(
        repository,
        {"site-a": [_pool("pool-a", gpu_model="A100")], "site-b": [_pool("pool-a")]},
        PublicationBinding("site-a", "vm", "pool-a", BACKED),
        _listing(),
        capacity,
    )

    # The shape names its model, so another model is another listing's source.
    assert result.outcome == "declared_mismatch"
    assert result.differing_fields == ("source",)
    assert capacity.asked == []


async def test_a_match_only_in_another_pool_is_not_a_match(repository):
    result = await _check(
        repository,
        {"site-a": [_pool("pool-b")]},
        PublicationBinding("site-a", "vm", "pool-a", BACKED),
        _listing(),
        _Capacity({}),
    )

    assert result.outcome == "declared_mismatch"


async def test_a_fungible_match_needs_one_member_large_enough(repository):
    pool = _pool("pool-a", members=(("r1", 2, 2), ("r2", 2, 2)))

    too_large = await _check(
        repository, {"site-a": [pool]},
        PublicationBinding("site-a", "vm", "pool-a", BACKED), _listing(gpu_count=4), _Capacity({}),
    )
    fits = await _check(
        repository, {"site-a": [pool]},
        PublicationBinding("site-a", "vm", "pool-a", BACKED), _listing(gpu_count=2), _Capacity({}),
    )

    assert too_large.outcome == "declared_mismatch"
    assert fits.outcome != "declared_mismatch"


async def test_an_unbacked_listing_makes_no_site_call(repository):
    tags = {"deliverable_modes": [], "advertisable_modes": ["vm"], "capacity_backing": "unbacked"}
    capacity = _Capacity({})

    result = await _check(
        repository,
        {"site-a": [_pool("pool-a", tags=tags, members=(("r1", 4, 0),))]},
        PublicationBinding("site-a", "vm", "pool-a", UNBACKED),
        _listing(),
        capacity,
    )

    assert result == ListingSourceVerdict("matches")
    assert capacity.asked == []


async def test_a_backed_listing_with_nothing_free_is_declared_but_unavailable(repository):
    result = await _check(
        repository,
        {"site-a": [_pool("pool-a", members=(("r1", 4, 0),))]},
        PublicationBinding("site-a", "vm", "pool-a", BACKED),
        _listing(),
        _Capacity({"site-a": [{"resource_id": "pool-a-r1", "available_units": 0}]}),
    )

    assert result.outcome == "unavailable"


async def test_an_unloaded_site_projection_confirms_nothing(repository):
    capacity = _Capacity({})

    result = await _check(
        repository,
        {"site-b": [_pool("pool-a")]},
        PublicationBinding("site-a", "vm", "pool-a", BACKED),
        _listing(),
        capacity,
    )

    # Retryable, not a mismatch: nothing is known to be wrong with the listing.
    assert result.outcome == "unverifiable"
    assert capacity.asked == []


async def test_a_site_whose_capacity_cannot_be_read_confirms_nothing(repository):
    class _Unreachable(_Capacity):
        def site_client(self, site_id):
            raise ConnectionError("site unreachable")

    result = await _check(
        repository,
        {"site-a": [_pool("pool-a")]},
        PublicationBinding("site-a", "vm", "pool-a", BACKED),
        _listing(),
        _Unreachable({}),
    )

    assert result.outcome == "unverifiable"


# -- The source-confirmation window -------------------------------------------

_BACKED = PublicationBinding("site-a", "vm", "pool-a", BACKED)


def _at(state, family, seconds):
    """A clock ``seconds`` after the family's last confirmed poll."""
    confirmed = state.view("site-a", family).fetched_at
    return lambda: confirmed + timedelta(seconds=seconds)


async def _confirmed_check(repository, state, *, clock, window=None, capacity=None):
    listing = _listing()
    if await repository.load_listing_binding(listing_id=listing["listing_id"]) is None:
        await _bind(repository, _BACKED, listing)
    return await check_listing_source(
        repository=repository,
        listing_record=listing,
        binding=_BACKED,
        capacity_runtime=capacity
        or _Capacity({"site-a": [{"resource_id": "pool-a-r1", "available_units": 4}]}),
        site_projections=state,
        confirmation_window_seconds=window,
        clock=clock,
    )


async def test_a_loaded_generation_past_the_window_confirms_nothing(repository):
    """A generation no poll has reached stays `loaded`; the window is what
    bounds how long it confirms a listing."""
    state = await loaded_site_projection_state(
        {"site-a": FakeProjectionSite(resource_pools=[_pool("pool-a")])}
    )
    capacity = _Capacity({"site-a": [{"resource_id": "pool-a-r1", "available_units": 4}]})

    inside = await _confirmed_check(
        repository, state, clock=_at(state, RESOURCE_POOL, 15), window=15, capacity=capacity
    )
    past = await _confirmed_check(
        repository, state, clock=_at(state, RESOURCE_POOL, 16), window=15, capacity=capacity
    )

    assert inside == ListingSourceVerdict("matches")
    assert past.outcome == "unverifiable"
    assert "resource_pool" in past.reason
    # Refused before any availability read.
    assert capacity.asked == ["site-a"]


async def test_a_stale_bucket_family_beside_a_fresh_pool_family_confirms_nothing(repository):
    """Fungible availability is computed from the bucket family the site holds;
    a stale one is not dropped in favour of the pool rows."""
    site = FakeProjectionSite(resource_pools=[_pool("pool-a")], capacity_buckets=[])
    state = await loaded_site_projection_state({"site-a": site})
    site.capacity_buckets = None
    await state.poll_once()
    assert state.view("site-a", RESOURCE_POOL).state.value == "loaded"
    assert state.view("site-a", CAPACITY_BUCKET).state.value == "stale"
    capacity = _Capacity({"site-a": [{"resource_id": "pool-a-r1", "available_units": 4}]})

    result = await _confirmed_check(
        repository, state, clock=_at(state, RESOURCE_POOL, 0), window=15, capacity=capacity
    )

    assert result.outcome == "unverifiable"
    assert "capacity_bucket" in result.reason
    assert capacity.asked == []


async def test_a_site_serving_no_bucket_family_is_judged_on_its_pools_alone(repository):
    """A family the site holds no generation of is not read: fungible
    availability comes from the pool rows, as publication derives it."""
    state = await loaded_site_projection_state(
        {"site-a": FakeProjectionSite(resource_pools=[_pool("pool-a")])}
    )

    result = await _confirmed_check(
        repository, state, clock=_at(state, RESOURCE_POOL, 1), window=15
    )

    assert result == ListingSourceVerdict("matches")


async def test_a_failed_poll_confirms_nothing_although_the_generation_is_held(repository):
    site = FakeProjectionSite(resource_pools=[_pool("pool-a")])
    state = await loaded_site_projection_state({"site-a": site})
    site.failing = True
    await state.poll_once()

    result = await _confirmed_check(
        repository, state, clock=_at(state, RESOURCE_POOL, 0), window=15
    )

    assert result.outcome == "unverifiable"
    assert "stale" in result.reason


async def test_the_window_defaults_to_three_poll_intervals():
    with settings_overrides(**{"capacity.poll_interval": 7}):
        assert source_confirmation_seconds() == 21
    with settings_overrides(
        **{"capacity.poll_interval": 7, "capacity.source_confirmation_seconds": 600}
    ):
        assert source_confirmation_seconds() == 600


async def test_an_unstated_window_is_the_configured_one(repository):
    """With no window given, the check reads the configured window: three poll
    intervals here."""
    state = await loaded_site_projection_state(
        {"site-a": FakeProjectionSite(resource_pools=[_pool("pool-a")])}
    )
    with settings_overrides(**{"capacity.poll_interval": 7}):
        inside = await _confirmed_check(
            repository, state, clock=_at(state, RESOURCE_POOL, 21)
        )
        past = await _confirmed_check(repository, state, clock=_at(state, RESOURCE_POOL, 22))

    assert inside == ListingSourceVerdict("matches")
    assert past.outcome == "unverifiable"
