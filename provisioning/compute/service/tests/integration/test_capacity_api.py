"""Capacity API: the full reserve→commit→release lifecycle over HTTP.

Exercises the /api/v1/capacity surface the storefront's remote
SiteCapacityClient will speak — payload shapes here are the wire contract.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from market_site.ledger import ALLOCATION_MODE_EXCLUSIVE, ALLOCATION_MODE_SHAREABLE
from compute_provisioning_service.main import app


class CapacityApi:
    """Typed helper over the capacity endpoints (no raw HTTP in tests)."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def register(self, resource_id: str, **body: Any) -> dict:
        resp = await self._client.put(
            f"/api/v1/capacity/resources/{resource_id}", json=body
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    async def snapshot(self) -> list[dict]:
        resp = await self._client.get("/api/v1/capacity/snapshot")
        assert resp.status_code == 200, resp.text
        return resp.json()["resources"]

    async def probe(self, claim: dict) -> dict | None:
        resp = await self._client.post(
            "/api/v1/capacity/probe", json={"claim": claim}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["match"]

    async def reserve(
        self, claim: dict, deal_ref: dict, ttl_seconds: float | None = None
    ) -> dict | None:
        body: dict = {"claim": claim, "deal_ref": deal_ref}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        resp = await self._client.post("/api/v1/capacity/reservations", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()["reservation"]

    async def commit(
        self,
        capacity_reservation_id: str,
        *,
        resource_id: str,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
    ) -> dict:
        body: dict = {"resource_id": resource_id}
        if lease_start_utc is not None:
            body["lease_start_utc"] = lease_start_utc
        if lease_end_utc is not None:
            body["lease_end_utc"] = lease_end_utc
        resp = await self._client.post(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}/commit",
            json=body,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["reservation"]

    async def release(self, **body: Any) -> dict | None:
        resp = await self._client.post("/api/v1/capacity/releases", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()["reservation"]

    async def truncate(self, capacity_reservation_id: str, lease_end_utc: str) -> dict | None:
        resp = await self._client.post(
            f"/api/v1/capacity/reservations/{capacity_reservation_id}/truncate-lease",
            json={"lease_end_utc": lease_end_utc},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["reservation"]

    async def events(self, after: int = 0) -> tuple[list[dict], int]:
        resp = await self._client.get(
            "/api/v1/capacity/events", params={"after": after}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        return data["events"], data["latest_version"]


@pytest.fixture
async def capacity(client_and_queue) -> CapacityApi:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield CapacityApi(http)


@pytest.mark.asyncio
async def test_reserve_commit_release_lifecycle(capacity: CapacityApi):
    await capacity.register(
        "compute-kvm1-001",
        total_units=8,
        resource_subtype="h200",
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )

    assert (await capacity.snapshot())[0]["available_units"] == 8
    assert await capacity.probe({"gpu_model": "H200", "vm_host": "kvm1"}) is not None
    assert await capacity.probe({"gpu_model": "A100"}) is None

    reserved = await capacity.reserve(
        {"gpu_count": 3, "vm_host": "kvm1"},
        {"listing_id": "lst-1", "escrow_uid": "0xesc"},
    )
    # vm_host is intentionally opaque across this boundary (see
    # openspec/specs/site-capacity/spec.md's "Capacity accounting is
    # private to the site authority" requirement) -- the claim above
    # already proves vm_host-attribute matching selected the right
    # resource, evidenced by the unit counts below, not by reading a
    # physical-placement field back off the reservation.
    assert "vm_host" not in reserved
    assert reserved["available_gpu_count"] == 5
    assert (await capacity.snapshot())[0]["available_units"] == 5

    committed = await capacity.commit(
        reserved["capacity_reservation_id"],
        resource_id="compute-kvm1-001",
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
    )
    assert committed["state"] == "leased"

    truncated = await capacity.truncate(reserved["capacity_reservation_id"], "2026-06-01 00:00")
    assert truncated["lease_end_utc"] == "2026-06-01 00:00"

    released = await capacity.release(deal_ref={"escrow_uid": "0xesc"})
    assert released["state"] == "released"
    assert (await capacity.snapshot())[0]["available_units"] == 8

    events, latest = await capacity.events()
    assert [e["kind"] for e in events] == [
        "released", "reserved", "committed", "lease_truncated", "released",
    ]
    assert latest == events[-1]["version"]
    # Anonymity on the wire: events never carry deal context.
    # "dimensions" is anonymous capacity-delta data, not deal context,
    # so it belongs in the allowed set alongside kind/resource_id/version.
    assert all(set(e) <= {"version", "kind", "resource_id", "occurred_at", "dimensions"}
               for e in events)


@pytest.mark.asyncio
async def test_no_capacity_is_a_null_answer_not_an_error(capacity: CapacityApi):
    assert await capacity.reserve({"gpu_count": 1}, {}) is None
    assert await capacity.release(capacity_reservation_id="missing") is None


@pytest.mark.asyncio
async def test_vm_and_bare_metal_claims_use_domain_attributes(capacity: CapacityApi):
    await capacity.register(
        "bare-metal-node-1",
        total_units=1,
        attributes={
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )

    assert await capacity.probe({"gpu_count": 1, "vm_host": "kvm1"}) is None
    reserved = await capacity.reserve(
        {
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        {"escrow_uid": "0xbm-capacity"},
    )

    assert reserved is not None
    assert "resource_id" not in reserved
    assert "vm_host" not in reserved


@pytest.mark.asyncio
async def test_capacity_snapshot_blocks_cross_mode_siblings(capacity: CapacityApi):
    await capacity.register(
        "compute-host-1",
        total_units=8,
        resource_subtype="h200",
        attributes={
            "vm_host": "kvm1",
            "gpu_model": "H200",
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_SHAREABLE,
        },
    )
    await capacity.register(
        "bare-metal-node-1",
        total_units=1,
        resource_subtype="h200",
        attributes={
            "machine_id": "node-1",
            "gpu_model": "H200",
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )

    initial = {row["resource_id"]: row for row in await capacity.snapshot()}
    assert initial["compute-host-1"]["available_units"] == 8
    assert initial["bare-metal-node-1"]["available_units"] == 1

    reserved = await capacity.reserve(
        {"gpu_count": 2, "vm_host": "kvm1"},
        {"escrow_uid": "0xvm-cross-mode"},
    )

    assert reserved is not None
    blocked = {row["resource_id"]: row for row in await capacity.snapshot()}
    assert blocked["compute-host-1"]["available_units"] == 6
    assert blocked["bare-metal-node-1"]["available_units"] == 0
    assert await capacity.probe({
        "physical_host_id": "host-physical-1",
        "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
    }) is None

    released = await capacity.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    assert released is not None
    restored = {row["resource_id"]: row for row in await capacity.snapshot()}
    assert restored["compute-host-1"]["available_units"] == 8
    assert restored["bare-metal-node-1"]["available_units"] == 1


@pytest.mark.asyncio
async def test_register_lease_attaches_to_ledger_reservation(capacity: CapacityApi):
    """POST /leases records the lease tail on the reservation row — the
    leases surface is a view over the ledger."""
    from compute_provisioning_service import container as _container_module

    await capacity.register(
        "compute-kvm1-001", total_units=8, attributes={"vm_host": "kvm1"},
    )
    reserved = await capacity.reserve(
        {"gpu_count": 1, "vm_host": "kvm1"},
        {"escrow_uid": "0xlease"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post("/api/v1/leases/", json={
            "resource_id": "compute-kvm1-001",
            "capacity_reservation_id": reserved["capacity_reservation_id"],
            "escrow_uid": "0xlease",
            "vm_host": "kvm1",
            "vm_target": "tenant-led1",
            "lease_end_utc": "2099-01-01T00:00:00Z",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] == reserved["capacity_reservation_id"]
        assert body["status"] == "active"

        listing = await http.get("/api/v1/leases/")
        assert listing.json()["total"] == 1
        assert listing.json()["leases"][0]["id"] == reserved["capacity_reservation_id"]

    ledger = _container_module.resolved_capacity_ledger_service
    row = ledger.get_reservation(reserved["capacity_reservation_id"])
    assert row["vm_target"] == "tenant-led1"
    assert row["state"] == "leased"
    assert row["lease_end_utc"] == "2099-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_register_lease_without_ledger_reservation_404s(
    capacity: CapacityApi,
):
    """Every reservation lives in the ledger; an unknown reservation means
    the hold lapsed or was already released — registration refuses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post("/api/v1/leases/", json={
            "resource_id": "compute-legacy-001",
            "capacity_reservation_id": "local-alloc-1",
            "escrow_uid": "0xlegacy",
            "vm_host": "kvm1",
            "vm_target": "tenant-leg1",
            "lease_end_utc": "2099-01-01T00:00:00Z",
        })
        assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_commit_unknown_reservation_404s(capacity: CapacityApi):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post(
            "/api/v1/capacity/reservations/missing/commit",
            json={"resource_id": "r", "lease_end_utc": "2099-01-01 00:00"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_site_resource_pools_projection_surfaces_pool_metadata(
    capacity: CapacityApi, client_and_queue,
):
    """Proves the full path, through both canonical typed clients rather
    than a direct DB insert on the write side or a raw HTTP call on the
    read side:

    ProvisioningClient.create_pool(default_vm_* in provider_config)
        -> real /api/v1/pools API -> real AnsiblePoolConfigHandler -> DB
        -> resource-pool projection
        -> SiteCapacityClient.resource_pool_projection()

    default_vm_* must be settable through the admin API and visible
    through the storefront's actual projection consumer, not only
    reachable by writing directly to the database or reading an HTTP
    route by hand.
    """
    from compute_provisioning import PoolCreate
    from market_site_client import SiteCapacityClient
    from compute_provisioning_service.db.models import Host
    from compute_provisioning_service.container import container

    provisioning_client, _ = client_and_queue
    await provisioning_client.create_pool(
        PoolCreate(
            id="hetzner-eu",
            label="Hetzner EU",
            provider="ansible",
            provider_config={
                "playbook_path": "playbooks/vm-operations.yaml",
                "default_vm_ram": 65536,
                "default_vm_vcpus": 16,
                "default_vm_disk_size": "500G",
            },
        )
    )

    # The resource-pool projection is built from Host rows (see
    # capacity_inventory.load_capacity_resource_inventory), not directly
    # from the ledger's registered resources -- a Host row is required
    # for anything to appear here at all. No typed client covers Host
    # creation against an arbitrary pool in this fixture set, so this
    # part still goes through the DB directly.
    with container.session_factory()() as db:
        db.add(Host(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="root",
            ssh_key_value="/dev/null", gpu_count=8, gpu_model="H200",
            pool_id="hetzner-eu",
        ))
        db.commit()

    await capacity.register(
        "compute-kvm1-001",
        pool_id="hetzner-eu",
        total_units=8,
        resource_subtype="h200",
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )

    remote = SiteCapacityClient("http://test", transport=ASGITransport(app=app))
    data = await remote.resource_pool_projection()
    rows = data["resource_pools"]
    pool_row = next(row for row in rows if row["resource_pool_id"] == "hetzner-eu")

    assert pool_row["pool_metadata"]["label"] == "Hetzner EU"
    assert pool_row["pool_metadata"]["enabled"] is True
    assert pool_row["pool_metadata"]["mechanism"] == "ansible"
    assert pool_row["pool_metadata"]["pool_views"] == {
        "vm.ansible_pool_defaults.v1": {
            "default_vm_ram": 65536,
            "default_vm_vcpus": 16,
            "default_vm_disk_size": "500G",
        },
    }
    # Host.gpu_model -> capacity_inventory._project_host -> resource-pool
    # projection's per-resource attributes -> the real SiteCapacityClient
    # response. Distinct from the ledger resource's own attributes dict
    # (registered above) -- proves the Host column specifically survives
    # the full producer -> client path, not just the ledger-side value.
    resource_row = next(
        r for r in pool_row["resources"] if r["physical_resource_id"] == "compute-kvm1-001"
    )
    assert resource_row["attributes"]["gpu_model"] == "H200"


@pytest.mark.asyncio
async def test_site_resource_pools_projection_surfaces_region_sla_pricing_policy_tags(
    capacity: CapacityApi, client_and_queue,
):
    """POOLS-8 Section 6's region/SLA/pricing hints need no new wire
    shape -- they're just more keys inside the already-projected
    `policy_tags` dict (see the pool-metadata test above) -- but they
    hadn't been proven through the real producer -> client path this
    specific way before. Proves the full path:

    ProvisioningClient.create_pool(policy_tags={region, sla, pricing})
        -> real /api/v1/pools API -> real ResourcePoolService -> DB
        -> resource-pool projection
        -> SiteCapacityClient.resource_pool_projection()
    """
    from compute_provisioning import PoolCreate
    from market_site_client import SiteCapacityClient
    from compute_provisioning_service.db.models import Host
    from compute_provisioning_service.container import container

    provisioning_client, _ = client_and_queue
    await provisioning_client.create_pool(
        PoolCreate(
            id="hetzner-eu",
            label="Hetzner EU",
            provider="ansible",
            policy_tags={
                "region": "California, US",
                "sla": 99.9,
                "pricing": {"gpu": {"H200": {"min_price": "5.00"}}},
            },
            provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
        )
    )

    with container.session_factory()() as db:
        db.add(Host(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="root",
            ssh_key_value="/dev/null", gpu_count=8, gpu_model="H200",
            pool_id="hetzner-eu",
        ))
        db.commit()

    await capacity.register(
        "compute-kvm1-001",
        pool_id="hetzner-eu",
        total_units=8,
        resource_subtype="h200",
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )

    remote = SiteCapacityClient("http://test", transport=ASGITransport(app=app))
    data = await remote.resource_pool_projection()
    rows = data["resource_pools"]
    pool_row = next(row for row in rows if row["resource_pool_id"] == "hetzner-eu")

    assert pool_row["pool_metadata"]["policy_tags"] == {
        "region": "California, US",
        "sla": 99.9,
        "pricing": {"gpu": {"H200": {"min_price": "5.00"}}},
    }


@pytest.mark.asyncio
async def test_site_resource_pools_projection_omits_pool_views_with_no_defaults(
    capacity: CapacityApi,
):
    """A pool with no configured VM size defaults gets pool_metadata (from
    ResourcePool's own columns) but no pool_views key at all -- read
    through the real SiteCapacityClient, not a raw HTTP call."""
    from market_site_client import SiteCapacityClient
    from compute_provisioning_service.container import container
    from compute_provisioning_service.db.models import Host

    with container.session_factory()() as db:
        db.add(Host(
            name="kvm1", kvm_host="10.0.0.1", ssh_user="root",
            ssh_key_value="/dev/null", gpu_count=8, pool_id="default",
        ))
        db.commit()

    await capacity.register(
        "compute-kvm1-001",
        pool_id="default",
        total_units=8,
        attributes={"vm_host": "kvm1"},
    )

    remote = SiteCapacityClient("http://test", transport=ASGITransport(app=app))
    data = await remote.resource_pool_projection()
    rows = data["resource_pools"]
    default_row = next(row for row in rows if row["resource_pool_id"] == "default")

    assert "pool_views" not in default_row["pool_metadata"]


@pytest.mark.asyncio
async def test_site_capacity_buckets_projection_through_the_real_client(
    capacity: CapacityApi,
):
    """Proves the real `SiteCapacityClient.capacity_bucket_projection()`
    wire contract end to end, mirroring `resource_pool_projection()`'s own
    proof above -- capacity buckets are a first-class fungible-mode
    publication input and need the same real-client coverage. Proves the
    full path:

    two registered resources with different availability
        -> real /api/v1/capacity/site-capacity-buckets route
        -> real SiteCapacityClient.capacity_bucket_projection()

    and that the response has the exact shape reconciler.py's
    `_fungible_availability_from_buckets` actually consumes
    (`resource_pool_id`, `available.gpu_count`, `resource_count`,
    `grouping_attributes`).
    """
    from market_site_client import SiteCapacityClient

    await capacity.register(
        "compute-kvm1-001",
        pool_id="hetzner-eu",
        total_units=8,
        resource_subtype="h200",
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )
    await capacity.register(
        "compute-kvm1-002",
        pool_id="hetzner-eu",
        total_units=6,
        resource_subtype="h200",
        attributes={"vm_host": "kvm1-b", "gpu_model": "H200"},
    )

    remote = SiteCapacityClient("http://test", transport=ASGITransport(app=app))
    data = await remote.capacity_bucket_projection()
    buckets = [
        b for b in data["capacity_buckets"] if b.get("resource_pool_id") == "hetzner-eu"
    ]

    # Two freshly-registered resources with different capacity (hence
    # different current availability) form two distinct buckets, each
    # resource_count=1 -- not one bucket summing to 14, which is exactly
    # the shape `_fungible_availability_from_buckets` relies on to
    # compute a per-member ceiling rather than a pool total.
    by_available = {b["available"]["gpu_count"]: b for b in buckets}
    assert set(by_available) == {8, 6}
    assert by_available[8]["resource_count"] == 1
    assert by_available[6]["resource_count"] == 1
    assert by_available[8]["grouping_attributes"].get("gpu_model") == "H200"
