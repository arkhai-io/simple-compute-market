from __future__ import annotations

from arkhai_bare_metal_storefront.site_capacity import BareMetalSiteCapacity


class _Remote:
    def __init__(self, site_id: str, *, available: bool = True) -> None:
        self.site_id = site_id
        self.revision = 1
        self.digest = f"digest-{site_id}-1"
        self.available = available
        self.fail_versions = False
        self.reserve_result = None
        self.topology_handler = None

    def set_topology_error_handler(self, handler):
        self.topology_handler = handler

    async def snapshot(self):
        return [{"resource_id": f"resource-{self.site_id}", "available_units": 1}]

    async def reserve(self, **_kwargs):
        return self.reserve_result

    async def resource_pool_projection_version(self):
        if self.fail_versions:
            raise RuntimeError(f"{self.site_id} unavailable")
        return {"revision": self.revision, "digest": self.digest}

    async def resource_pool_projection(self):
        resources = []
        if self.available:
            resources.append({
                "resource_id": f"resource-{self.site_id}",
                "publication_views": {
                    "bare_metal.v1": {
                        "physical_resource_id": f"resource-{self.site_id}",
                        "physical_host_id": f"host-{self.site_id}",
                        "machine_id": f"machine-{self.site_id}",
                        "available": True,
                        "allocation_mode": "exclusive",
                        "access_methods": ["ssh"],
                        "capacity": {"gpu_count": 1},
                        "capabilities": {},
                    },
                },
            })
        return {
            "revision": self.revision,
            "digest": self.digest,
            "resource_pools": resources,
        }

    async def capacity_bucket_projection_version(self):
        if self.fail_versions:
            raise RuntimeError(f"{self.site_id} unavailable")
        return {"revision": self.revision, "digest": self.digest}

    async def capacity_bucket_projection(self):
        return {
            "revision": self.revision,
            "digest": self.digest,
            "capacity_buckets": [],
        }


async def test_loads_and_retains_independent_site_generations() -> None:
    east = _Remote("east")
    west = _Remote("west")
    capacity = BareMetalSiteCapacity({"east": east, "west": west})

    await capacity.load()
    initial = capacity.bare_metal_projections()

    assert [projection.site_id for projection in initial] == ["east", "west"]
    assert initial[0].resources[0].machine_id == "machine-east"
    assert initial[1].resources[0].machine_id == "machine-west"
    assert capacity.projection_health() == "ok"
    assert east.topology_handler is not None
    assert west.topology_handler is not None

    east.fail_versions = True
    west.revision = 2
    west.digest = "digest-west-2"
    west.available = False
    await capacity.poll_once()

    retained = capacity.bare_metal_projections()
    assert retained[0].site_id == "east"
    assert retained[0].stale is True
    assert retained[0].resources[0].machine_id == "machine-east"
    assert retained[1].site_id == "west"
    assert retained[1].revision == 2
    assert retained[1].resources == []
    assert capacity.projection_health() == "stale"


async def test_reservation_uses_trusted_multi_site_clients() -> None:
    east = _Remote("east")
    west = _Remote("west")
    west.reserve_result = {
        "capacity_reservation_id": "reservation-west",
        "resource_id": "resource-west",
    }
    capacity = BareMetalSiteCapacity({"east": east, "west": west})

    reserved = await capacity.reserve(
        claim={"resource_type": "bare_metal", "units": 1},
        deal_ref={"agreement_ref": "agreement-1"},
    )

    assert reserved == {
        "capacity_reservation_id": "reservation-west",
        "resource_id": "resource-west",
        "site": "west",
    }
    assert capacity.client_for_site("west") is west
