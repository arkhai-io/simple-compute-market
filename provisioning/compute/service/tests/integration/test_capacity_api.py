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
from market_site_client import (
    SiteCapacityAdminClient,
    SiteCapacityAdminClientError,
    SiteCapacityAuthenticationError,
    SiteCapacityClient,
    SiteCapacityClientError,
)
from compute_provisioning import PoolCreate
from market_resource_pools import resolve_pool_declarations
from vm_provisioning_operator.models import HostCreate

from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER


def _site_capacity_client(base_url: str, *, transport):
    return SiteCapacityClient(
        base_url,
        STOREFRONT_SIGNER,
        SERVICE_AUTHORITIES,
        transport=transport,
    )


class CapacityApi:
    """The capacity surface as the canonical typed clients present it.

    Every call goes through ``SiteCapacityAdminClient`` (registration) or
    ``SiteCapacityClient`` (everything a storefront does), so a route, body,
    or response-shape change breaks these tests through the clients rather
    than through a second, test-local copy of the wire contract. This class
    only shortens call sites; it builds no request of its own and holds no
    raw HTTP client, so a test that bypasses the clients has to say so
    locally.
    """

    def __init__(
        self,
        admin: SiteCapacityAdminClient,
        site: SiteCapacityClient,
    ) -> None:
        self.admin = admin
        self.site = site

    async def register(self, resource_id: str, **declaration: Any) -> dict:
        return await self.admin.register_resource(resource_id, **declaration)

    async def snapshot(self) -> list[dict]:
        return await self.site.snapshot()

    async def probe(self, claim: dict) -> dict | None:
        return await self.site.probe(claim=claim)

    async def reserve(
        self, claim: dict, deal_ref: dict, ttl_seconds: float | None = None
    ) -> dict | None:
        return await self.site.reserve(
            claim=claim, deal_ref=deal_ref, ttl_seconds=ttl_seconds
        )

    async def commit(
        self,
        capacity_reservation_id: str,
        *,
        resource_id: str,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
    ) -> None:
        await self.site.commit(
            capacity_reservation_id=capacity_reservation_id,
            resource_id=resource_id,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
        )

    async def release(self, **target: Any) -> dict | None:
        return await self.site.release(**target)

    async def truncate(self, capacity_reservation_id: str, lease_end_utc: str) -> dict | None:
        return await self.site.truncate_lease(
            capacity_reservation_id=capacity_reservation_id,
            lease_end_utc=lease_end_utc,
        )

    async def events(self, after: int = 0) -> tuple[list[dict], int]:
        return await self.site.events_after(after)


async def _create_pool(provisioning_client, pool_id: str) -> None:
    """A declaration's pool must exist; create it through the operator client."""
    await provisioning_client.create_pool(PoolCreate(
        id=pool_id, label=pool_id, provider="ansible",
        policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
        provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
    ))


@pytest.fixture
async def capacity(client_and_queue) -> CapacityApi:
    transport = ASGITransport(app=app)
    admin = SiteCapacityAdminClient(
        "http://test", STOREFRONT_SIGNER, SERVICE_AUTHORITIES, transport=transport,
    )
    site = _site_capacity_client("http://test", transport=transport)
    return CapacityApi(admin, site)


@pytest.mark.asyncio
async def test_the_claim_names_the_offering_mode_through_the_canonical_client(
    capacity: CapacityApi,
):
    """The offering mode a storefront names crosses the site boundary through
    `SiteCapacityClient` and is persisted on the reservation as sent, not
    re-derived from the resource or reported under a second key."""
    await capacity.register(
        "site-claim-1", pool_id="default",
        total_units=4,
        host_id="kvm1",
        attributes={"gpu_model": "H200"},
    )

    reservation = await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 1, "host_id": "kvm1"},
        {"escrow_uid": "escrow-claim-1"},
    )

    assert reservation is not None
    assert reservation["offering_mode"] == "vm"
    assert "executor_kind" not in reservation


@pytest.mark.asyncio
async def test_a_claim_omitting_the_offering_mode_is_refused(capacity: CapacityApi):
    """The field is required, so its absence is refused before any resource is
    matched — never inferred from `host_id` or a default. The refusal reaches
    the storefront as the client's own error, carrying the site's status."""
    await capacity.register(
        "site-claim-2", pool_id="default", total_units=4, host_id="kvm1",
        attributes={}
    )

    with pytest.raises(SiteCapacityClientError) as refused:
        await capacity.reserve({"gpu_count": 1, "host_id": "kvm1"}, {})

    assert refused.value.status_code == 422


@pytest.mark.asyncio
async def test_a_claim_naming_the_mode_under_the_retired_key_is_refused(
    capacity: CapacityApi,
):
    """The retired key is not the required one, so the claim carries no
    offering mode and is refused rather than being honoured under a second
    spelling."""
    await capacity.register(
        "site-claim-3", pool_id="default", total_units=4, host_id="kvm1",
        attributes={}
    )

    with pytest.raises(SiteCapacityClientError) as refused:
        await capacity.reserve(
            {"executor_kind": "vm", "gpu_count": 1, "host_id": "kvm1"}, {}
        )

    assert refused.value.status_code == 422


@pytest.mark.asyncio
async def test_reserve_commit_release_lifecycle(capacity: CapacityApi):
    await capacity.register(
        "compute-kvm1-001", pool_id="default",
        total_units=8,
        resource_subtype="h200",
        host_id="kvm1",
        attributes={"gpu_model": "H200"},
    )

    assert (await capacity.snapshot())[0]["available_units"] == 8
    assert await capacity.probe(
        {"offering_mode": "vm", "gpu_model": "H200", "host_id": "kvm1"}
    ) is not None
    assert await capacity.probe(
        {"offering_mode": "vm", "gpu_model": "A100"}
    ) is None

    reserved = await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 3, "host_id": "kvm1"},
        {"listing_id": "lst-1", "escrow_uid": "0xesc"},
    )
    # host_id is intentionally opaque across this boundary (see
    # openspec/specs/site-capacity/spec.md's "Capacity accounting is
    # private to the site authority" requirement) -- the claim above
    # already proves host_id-attribute matching selected the right
    # resource, evidenced by the unit counts below, not by reading a
    # physical-placement field back off the reservation.
    assert "host_id" not in reserved
    assert reserved["available_gpu_count"] == 5
    assert (await capacity.snapshot())[0]["available_units"] == 5

    # The client's commit returns nothing; the committed reservation is read
    # back through the same client, as a storefront would.
    await capacity.commit(
        reserved["capacity_reservation_id"],
        resource_id="compute-kvm1-001",
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
    )
    committed = await capacity.site.get_reservation(reserved["capacity_reservation_id"])
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
    assert await capacity.reserve({"offering_mode": "vm", "gpu_count": 1}, {}) is None
    assert await capacity.release(capacity_reservation_id="missing") is None


@pytest.mark.asyncio
async def test_vm_and_bare_metal_claims_use_domain_attributes(capacity: CapacityApi):
    await capacity.register(
        "bare-metal-node-1", pool_id="default", host_id="bm-node-1",
        total_units=1,
        attributes={
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )

    assert await capacity.probe(
        {"offering_mode": "vm", "gpu_count": 1, "host_id": "kvm1"}
    ) is None
    reserved = await capacity.reserve(
        {
            "offering_mode": "bare_metal",
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        {"escrow_uid": "0xbm-capacity"},
    )

    assert reserved is not None
    assert "resource_id" not in reserved
    assert "host_id" not in reserved


@pytest.mark.asyncio
async def test_capacity_snapshot_blocks_cross_mode_siblings(capacity: CapacityApi):
    await capacity.register(
        "compute-host-1", pool_id="default",
        total_units=8,
        resource_subtype="h200",
        host_id="kvm1",
        attributes={
            "gpu_model": "H200",
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_SHAREABLE,
        },
    )
    await capacity.register(
        "bare-metal-node-1", pool_id="default",
        total_units=1,
        resource_subtype="h200",
        host_id="node-1",
        attributes={
            "gpu_model": "H200",
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
    )

    initial = {row["resource_id"]: row for row in await capacity.snapshot()}
    assert initial["compute-host-1"]["available_units"] == 8
    assert initial["bare-metal-node-1"]["available_units"] == 1

    reserved = await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 2, "host_id": "kvm1"},
        {"escrow_uid": "0xvm-cross-mode"},
    )

    assert reserved is not None
    blocked = {row["resource_id"]: row for row in await capacity.snapshot()}
    assert blocked["compute-host-1"]["available_units"] == 6
    assert blocked["bare-metal-node-1"]["available_units"] == 0
    assert await capacity.probe({
        "offering_mode": "bare_metal",
        "physical_host_id": "host-physical-1",
        "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
    }) is None

    released = await capacity.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    assert released is not None
    restored = {row["resource_id"]: row for row in await capacity.snapshot()}
    assert restored["compute-host-1"]["available_units"] == 8
    assert restored["bare-metal-node-1"]["available_units"] == 1


@pytest.mark.asyncio
async def test_commit_unknown_reservation_404s(capacity: CapacityApi):
    with pytest.raises(SiteCapacityClientError) as refused:
        await capacity.commit(
            "missing", resource_id="r", lease_end_utc="2099-01-01 00:00"
        )

    assert refused.value.status_code == 404


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
    provisioning_client, _ = client_and_queue
    await provisioning_client.create_pool(
        PoolCreate(
            id="hetzner-eu",
            label="Hetzner EU",
            provider="ansible",
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
            provider_config={
                "playbook_path": "playbooks/vm-operations.yaml",
                "default_vm_ram": 65536,
                "default_vm_vcpus": 16,
                "default_vm_disk_size": "500G",
            },
        )
    )

    await capacity.register(
        "compute-kvm1-001",
        pool_id="hetzner-eu",
        total_units=8,
        resource_subtype="h200",
        host_id="kvm1",
        attributes={"gpu_model": "H200"},
    )

    remote = _site_capacity_client("http://test", transport=ASGITransport(app=app))
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
    # The declaration's own attribute -> resource-pool projection -> the real
    # SiteCapacityClient response.
    resource_row = next(
        r for r in pool_row["resources"] if r["physical_resource_id"] == "compute-kvm1-001"
    )
    assert resource_row["attributes"]["gpu_model"] == "H200"


@pytest.mark.asyncio
async def test_site_resource_pools_projection_surfaces_region_sla_pricing_policy_tags(
    capacity: CapacityApi, client_and_queue,
):
    """`region`/`sla`/`pricing` need no new wire shape -- they're just
    more keys inside the already-projected `policy_tags` dict (see the
    pool-metadata test above). Proves the full path:

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
                "advertisable_modes": [],
                "capacity_backing": "backed",
                "region": "California, US",
                "sla": 99.9,
                "pricing": {"gpu": {"H200": {"min_price": "5.00"}}},
            },
            provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
        )
    )

    with container.session_factory()() as db:
        db.add(Host(
            host_id="kvm1", ssh_host="10.0.0.1", ssh_user="root",
            ssh_key_value="/dev/null", gpu_count=8, gpu_model="H200",
            pool_id="hetzner-eu",
        ))
        db.commit()

    await capacity.register(
        "compute-kvm1-001",
        pool_id="hetzner-eu",
        total_units=8,
        resource_subtype="h200",
        host_id="kvm1",
        attributes={"gpu_model": "H200"},
    )

    remote = _site_capacity_client("http://test", transport=ASGITransport(app=app))
    data = await remote.resource_pool_projection()
    rows = data["resource_pools"]
    pool_row = next(row for row in rows if row["resource_pool_id"] == "hetzner-eu")

    assert pool_row["pool_metadata"]["policy_tags"] == {
        "advertisable_modes": [],
        "capacity_backing": "backed",
        "region": "California, US",
        "sla": 99.9,
        "pricing": {"gpu": {"H200": {"min_price": "5.00"}}},
    }


@pytest.mark.asyncio
async def test_site_resource_pools_projection_declares_every_pool(
    capacity: CapacityApi, client_and_queue,
):
    """Every projected pool carries both advertisement and backing
    declarations, and each resolves through the shared resolver.

    A consumer distinguishes a site predating these declarations (no pool
    carries them) from a defective one (some pool lacks them) only because
    the producer emits them on every pool; that is a property of this side
    of the projection, which the consumer cannot verify on its own.
    """
    provisioning_client, _ = client_and_queue
    await provisioning_client.create_pool(PoolCreate(
        id="bare-metal-west",
        label="Bare metal west",
        provider="ansible",
        policy_tags={
            "deliverable_modes": ["bare_metal", "vm"],
            "advertisable_modes": ["bare_metal"],
            "capacity_backing": "backed",
        },
        provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
    ))
    await capacity.register("default-001", pool_id="default", total_units=4, host_id="kvm1")
    await capacity.register(
        "west-001", pool_id="bare-metal-west", total_units=4, host_id="kvm2",
    )

    remote = _site_capacity_client("http://test", transport=ASGITransport(app=app))
    rows = (await remote.resource_pool_projection())["resource_pools"]

    resolved = {
        row["resource_pool_id"]: resolve_pool_declarations(
            row["pool_metadata"]["policy_tags"]
        )
        for row in rows
    }
    assert set(resolved) == {"default", "bare-metal-west"}
    assert resolved["bare-metal-west"].advertisable_modes == frozenset({"bare_metal"})
    assert all(declarations.backed for declarations in resolved.values())


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
            host_id="kvm1", ssh_host="10.0.0.1", ssh_user="root",
            ssh_key_value="/dev/null", gpu_count=8, pool_id="default",
        ))
        db.commit()

    await capacity.register(
        "compute-kvm1-001",
        pool_id="default",
        total_units=8,
        host_id="kvm1",
        attributes={},
    )

    remote = _site_capacity_client("http://test", transport=ASGITransport(app=app))
    data = await remote.resource_pool_projection()
    rows = data["resource_pools"]
    default_row = next(row for row in rows if row["resource_pool_id"] == "default")

    assert "pool_views" not in default_row["pool_metadata"]


@pytest.mark.asyncio
async def test_site_capacity_projection_version_endpoints_through_the_real_client(
    capacity: CapacityApi, client_and_queue,
):
    """The one gap left after the four projection-data tests above: the
    `_version()` siblings (a cheap poll-for-change check, not the full
    payload) had no real-client coverage of their own. Proves both
    through a real in-process app, and that each version's revision
    advances when the corresponding projection's own content changes."""
    from market_site_client import SiteCapacityClient
    from compute_provisioning_service.container import container
    from compute_provisioning_service.db.models import Host

    remote = _site_capacity_client("http://test", transport=ASGITransport(app=app))
    await _create_pool(client_and_queue[0], "version-pool")

    pool_version_before = await remote.resource_pool_projection_version()
    bucket_version_before = await remote.capacity_bucket_projection_version()
    assert "revision" in pool_version_before
    assert "digest" in pool_version_before
    assert "revision" in bucket_version_before
    assert "digest" in bucket_version_before

    with container.session_factory()() as db:
        db.add(Host(
            host_id="kvm-version-test", ssh_host="10.0.0.2", ssh_user="root",
            ssh_key_value="/dev/null", gpu_count=4, pool_id="version-pool",
        ))
        db.commit()
    await capacity.register(
        "compute-version-test-001",
        pool_id="version-pool",
        total_units=4,
        host_id="kvm-version-test",
        attributes={},
    )

    pool_version_after = await remote.resource_pool_projection_version()
    bucket_version_after = await remote.capacity_bucket_projection_version()
    assert pool_version_after != pool_version_before
    assert bucket_version_after != bucket_version_before


@pytest.mark.asyncio
async def test_site_capacity_buckets_projection_through_the_real_client(
    capacity: CapacityApi, client_and_queue,
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

    await _create_pool(client_and_queue[0], "hetzner-eu")
    await capacity.register(
        "compute-kvm1-001",
        pool_id="hetzner-eu",
        total_units=8,
        resource_subtype="h200",
        host_id="kvm1",
        attributes={"gpu_model": "H200"},
    )
    await capacity.register(
        "compute-kvm1-002",
        pool_id="hetzner-eu",
        total_units=6,
        resource_subtype="h200",
        host_id="kvm1-b",
        attributes={"gpu_model": "H200"},
    )

    remote = _site_capacity_client("http://test", transport=ASGITransport(app=app))
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



async def test_a_registration_restating_a_field_as_an_attribute_is_refused(
    capacity: CapacityApi,
):
    """The admin client sends any attributes mapping, so the refusal is
    observed through it: a 422 the site acknowledged, and nothing written."""
    with pytest.raises(SiteCapacityAdminClientError) as refused:
        await capacity.register(
            "restated", pool_id="default", total_units=1,
            attributes={"host_id": "kvm1", "gpu_model": "H200"},
        )

    assert not isinstance(refused.value, SiteCapacityAuthenticationError)
    assert refused.value.status_code == 422
    assert "host_id" in str(refused.value)
    assert await capacity.snapshot() == []

async def test_a_registration_without_a_pool_is_rejected(capacity: CapacityApi):
    """Rejection-path test (docs/development/TESTING.md): the typed admin
    client requires ``pool_id`` and cannot construct this registration, so
    the body is posted by hand to prove the server's own validation boundary
    refuses it. Status code only."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        resp = await http.put(
            "/api/v1/capacity/resources/no-pool", json={"total_units": 1},
        )
    assert resp.status_code == 422


async def test_the_resource_pool_projection_publishes_declarations_not_hosts(
    capacity: CapacityApi, client_and_queue,
):
    """An INI host gains a derived declaration and is projected from it, with
    live availability; a host registered with no declaration is not projected
    at all. Written through ProvisioningClient, read through
    SiteCapacityClient.resource_pool_projection."""
    provisioning_client, _ = client_and_queue
    await provisioning_client.import_hosts_from_text(
        "[kvm_hosts]\n"
        "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
        "ansible_ssh_private_key_file=/keys/id  gpus=4  gpu_model=H200\n",
        ssh_key_type="path",
    )
    await provisioning_client.register_host(HostCreate(
        host_id="kvm2", ssh_host="10.0.0.2", ssh_user="ubuntu",
        ssh_key_value="/keys/id", gpu_count=8,
    ))
    reserved = await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 1, "resource_id": "kvm1"}, {}
    )
    assert reserved is not None

    projection = await capacity.site.resource_pool_projection()

    resources = {
        row["physical_resource_id"]: row
        for pool in projection["resource_pools"]
        for row in pool["resources"]
    }
    assert set(resources) == {"kvm1"}
    assert resources["kvm1"]["capacity"] == {"gpu_count": 4}
    assert resources["kvm1"]["available"] == {"gpu_count": 3}
    assert resources["kvm1"]["attributes"]["gpu_model"] == "H200"
    assert "gpu_count" not in resources["kvm1"]["attributes"]


async def test_a_registration_naming_an_unknown_pool_is_refused(capacity: CapacityApi):
    """The same rule a capacity document meets: the declaration's pool must
    exist, and the refusal writes nothing."""
    with pytest.raises(SiteCapacityAdminClientError) as refused:
        await capacity.register("r-nowhere", pool_id="no-such-pool", total_units=1)

    assert not isinstance(refused.value, SiteCapacityAuthenticationError)
    assert refused.value.status_code == 422
    assert "no-such-pool" in str(refused.value)
    assert await capacity.snapshot() == []


async def test_a_declaration_naming_no_compute_dimension_is_stored_as_declared(
    capacity: CapacityApi,
):
    """Through the typed admin client: a declaration naming only memory has no
    GPU dimension added, and no scalar total, since it names no dimension
    the scalar mirrors."""
    resource = await capacity.register(
        "memory-only", pool_id="default", capacity={"ram_gb": 64},
    )

    assert resource["capacity"] == {"ram_gb": 64}
    assert resource["value"] is None
    assert resource["available_units"] is None
    (listed,) = await capacity.admin.list_resources()
    assert listed["capacity"] == {"ram_gb": 64}


async def test_a_held_resource_moves_pools_only_once_released(
    capacity: CapacityApi, client_and_queue,
):
    """Both halves in one test, so the refusal cannot be mistaken for a
    resource that could never move."""
    await _create_pool(client_and_queue[0], "pool-b")
    await capacity.register("held", pool_id="default", host_id="kvm-held", total_units=4)
    reserved = await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 1, "resource_id": "held"}, {}
    )
    assert reserved is not None

    with pytest.raises(SiteCapacityAdminClientError) as refused:
        await capacity.register("held", pool_id="pool-b", host_id="kvm-held", total_units=4)
    assert refused.value.status_code == 409
    assert (await capacity.admin.list_resources())[0]["pool_id"] == "default"

    await capacity.release(capacity_reservation_id=reserved["capacity_reservation_id"])
    moved = await capacity.register("held", pool_id="pool-b", host_id="kvm-held", total_units=4)

    assert moved["pool_id"] == "pool-b"


async def test_a_declaration_naming_no_host_is_not_admitted_in_a_host_requiring_pool(
    capacity: CapacityApi,
):
    """The default pool's Ansible provider delivers through a host, so a
    declaration naming none is refused the ordinary way, while one naming a
    host is admitted. Registered and reserved through the canonical clients."""
    await capacity.register("no-host", pool_id="default", total_units=4)

    assert await capacity.probe({"offering_mode": "vm", "gpu_count": 1}) is None
    assert await capacity.reserve({"offering_mode": "vm", "gpu_count": 1}, {}) is None

    await capacity.register("hosted", pool_id="default", host_id="kvm1", total_units=4)
    reserved = await capacity.reserve({"offering_mode": "vm", "gpu_count": 1}, {})

    assert reserved is not None
    snapshot = {row["resource_id"]: row for row in await capacity.snapshot()}
    assert snapshot["no-host"]["available_units"] == 4
    assert snapshot["hosted"]["available_units"] == 3



async def test_a_declaration_naming_no_host_reaches_the_resource_pool_projection(
    capacity: CapacityApi, client_and_queue,
):
    """The projection is built from declarations, so one naming no host is
    visible to storefronts with its declared shape, and no entry carries host
    connection identity. Registered and read through the canonical clients."""
    provisioning_client, _ = client_and_queue
    # The host record carries a GPU model; the declaration naming it does not.
    await provisioning_client.register_host(HostCreate(
        host_id="kvm1", ssh_host="10.0.0.1", public_host="203.0.113.10",
        ssh_user="ubuntu", ssh_key_value="/keys/id", gpu_model="H100",
    ))
    await capacity.register(
        "no-host", pool_id="default",
        capacity={"gpu_count": 2, "ram_gb": 64},
        attributes={"gpu_model": "H200"},
    )
    await capacity.register(
        "hosted", pool_id="default", host_id="kvm1", total_units=4,
    )

    projection = await capacity.site.resource_pool_projection()

    resources = {
        row["physical_resource_id"]: row
        for pool in projection["resource_pools"]
        for row in pool["resources"]
    }
    assert set(resources) == {"no-host", "hosted"}
    assert resources["no-host"]["capacity"] == {"gpu_count": 2, "ram_gb": 64}
    assert resources["no-host"]["attributes"] == {"gpu_model": "H200"}
    # A value only the host record holds never fills an undeclared attribute.
    assert resources["hosted"]["attributes"] == {}
    for row in resources.values():
        assert "host_id" not in row["attributes"]
        assert "public_host" not in row["attributes"]
