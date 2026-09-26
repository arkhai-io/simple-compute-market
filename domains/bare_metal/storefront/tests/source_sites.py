"""A site authority double answering the projection a seeded listing came from.

Openings recheck a listing against its own site's projection, so a test that
seeds a listing directly supplies the site that would have published it: one
pool, one whole-machine Physical Resource, and the hardware and region the
listing fixtures publish. Built from the site-client and bare-metal contract
fixtures, so the projection is the shape a real site serves.
"""

from __future__ import annotations

from typing import Any

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
) -> dict[str, Any]:
    declared = dict(DECLARED_CAPACITY if capacity is None else capacity)
    resource = build_projected_resource(
        resource_id,
        capacity=declared,
        attributes={"gpu_model": gpu_model, "physical_host_id": physical_host_id},
        resource_type="compute.bare-metal",
        publication_views={
            "bare_metal.v2": build_bare_metal_publication_view(
                resource_id,
                pool_id=pool_id,
                host_id=host_id,
                physical_host_id=physical_host_id,
                capacity=declared,
            )
        },
    )
    row = build_resource_pool_row(
        pool_id,
        advertisable_modes=("bare_metal",),
        policy_tags={"region": region},
        resources=[resource],
    )
    return {"revision": 1, "digest": "digest-1", **build_resource_pool_projection([row])}


class SourceSite:
    def __init__(self, projection: dict[str, Any] | None = None, error: Exception | None = None):
        self.projection = projection if projection is not None else listing_source_projection()
        self.error = error
        self.calls = 0

    async def resource_pool_projection(self) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.projection


class SourceSites:
    """The trusted per-site clients a runtime composes, answering one site."""

    def __init__(self, site: SourceSite | None = None, *, site_id: str = "site-a") -> None:
        self.site_id = site_id
        self.source = site or SourceSite()
        self.reservation_sites: dict[str, str] = {}

    def site(self, site_id: str) -> SourceSite:
        assert site_id == self.site_id, site_id
        return self.source
