"""A site authority double answering the projection a seeded listing came from.

Openings recheck a listing against the projection the storefront holds for its
own site, so a test that seeds a listing directly supplies the site that would
have published it: one pool, one whole-machine Physical Resource, and the
hardware and region the listing fixtures publish. Built from the site-client and
bare-metal contract fixtures, so the projection is the shape a real site serves.
``source_projections`` is the storefront's held projection state over such
sites, which the app's startup loads with its first poll; a change a test makes
to a site reaches the state only when a poll runs, as in production.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core_storefront.aggregation import AggregateCapacityClient
from market_capacity_publication import SiteProjectionState
from market_resource_pools_contracts.backing import BACKED, CapacityBacking

from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from arkhai_bare_metal.fixtures.publication_view import build_bare_metal_publication_view
from market_site_client.fixtures.resource_pools import (
    build_projected_resource,
    build_resource_pool_projection,
    build_resource_pool_row,
)

#: The declaration behind ``LISTING_HARDWARE``: one unit holding its hardware.
DECLARED_CAPACITY = {
    "units": 1,
    "gpu_count": LISTING_HARDWARE["gpu_count"],
    "ram_gb": LISTING_HARDWARE["ram_gb"],
}


def listing_source_projection(
    *,
    pool_id: str = "pool-a",
    resource_id: str = "resource-1",
    host_id: str = "machine-1",
    physical_host_id: str = "physical-host-1",
    capacity: dict[str, Any] | None = None,
    gpu_model: str = LISTING_HARDWARE["gpu_model"],
    region: str | None = LISTING_HARDWARE["region"],
    available: bool = True,
    backing: CapacityBacking = BACKED,
) -> dict[str, Any]:
    """The seeded listing's site generation; ``backing`` is its pool's, whose
    delegate decides which delivery terms the view carries."""
    declared = dict(DECLARED_CAPACITY if capacity is None else capacity)
    resource = build_projected_resource(
        resource_id,
        capacity=declared,
        attributes={"gpu_model": gpu_model, "physical_host_id": physical_host_id},
        resource_type="compute.bare-metal",
        publication_views={
            "bare_metal.v2": build_bare_metal_publication_view(
                resource_id,
                backing=backing,
                pool_id=pool_id,
                host_id=host_id,
                physical_host_id=physical_host_id,
                capacity=declared,
                available=available,
            )
        },
    )
    row = build_resource_pool_row(
        pool_id,
        capacity_backing=backing.label,
        advertisable_modes=("bare_metal",),
        policy_tags={"region": region},
        resources=[resource],
    )
    projection = build_resource_pool_projection([row])
    # A site's digest covers what it projects, so a changed declaration is a
    # new generation a poll fetches.
    digest = hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest()
    return {"revision": 1, "digest": f"digest-{digest[:16]}", **projection}


class SourceSite:
    """One site serving ``projection``, or failing with ``error``.

    It serves an empty capacity-bucket projection beside it, and ``calls``
    counts every call made to it, of either family.
    """

    def __init__(self, projection: dict[str, Any] | None = None, error: Exception | None = None):
        self.projection = projection if projection is not None else listing_source_projection()
        self.error = error
        self.calls = 0

    def _answer(self) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.projection

    async def resource_pool_projection_version(self) -> dict[str, Any]:
        answer = self._answer()
        return {"revision": answer["revision"], "digest": answer["digest"]}

    async def resource_pool_projection(self) -> dict[str, Any]:
        return self._answer()

    async def capacity_bucket_projection_version(self) -> dict[str, Any]:
        self._answer()
        return {"revision": 1, "digest": "buckets-1"}

    async def capacity_bucket_projection(self) -> dict[str, Any]:
        self._answer()
        return {"revision": 1, "digest": "buckets-1", "capacity_buckets": []}

    def set_topology_error_handler(self, _handler: Any) -> None:
        return None


class SourceSites:
    """The trusted per-site clients a runtime composes, answering one site."""

    def __init__(self, site: SourceSite | None = None, *, site_id: str = "site-a") -> None:
        self.site_id = site_id
        self.source = site or SourceSite()
        self.site_names = [site_id]
        self.reservation_sites: dict[str, str] = {}

    def site(self, site_id: str) -> SourceSite:
        assert site_id == self.site_id, site_id
        return self.source


def source_projections(
    *sites: SourceSite | tuple[str, SourceSite],
    on_resource_pool_change: Any = None,
) -> SiteProjectionState:
    """The storefront's held projection state over ``sites``, holding nothing yet.

    Each site is a ``SourceSite``, at ``site-a`` by default, or a pair naming its
    site ID; with none, one default ``SourceSite`` at ``site-a``.
    """
    named = dict(
        site if isinstance(site, tuple) else ("site-a", site)
        for site in (sites or (SourceSite(),))
    )
    return SiteProjectionState(
        AggregateCapacityClient(named),
        on_resource_pool_change=on_resource_pool_change or (lambda: None),
    )


async def loaded_source_projections(
    *sites: SourceSite | tuple[str, SourceSite],
) -> SiteProjectionState:
    """``source_projections`` after its first poll, as startup loads it."""
    state = source_projections(*sites)
    await state.poll_once()
    return state
