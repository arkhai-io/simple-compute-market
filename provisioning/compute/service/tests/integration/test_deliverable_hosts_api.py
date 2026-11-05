"""Disabling a host keeps new deliveries off it, across the running service.

A declaration in a backed pool whose provider needs a host is offered only
while the host it names is registered and enabled. Every step goes through the
canonical typed clients: hosts through the family client, pools through
``ResourcePoolClient``, declarations through ``SiteCapacityAdminClient``,
admission and projections through ``SiteCapacityClient``, and scheduling and
acceptance through ``ComputeProvisioningClient``. Host addresses are
documentation-range placeholders nothing connects to.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport

from compute_provisioning_ansible import ssh_connection
from compute_provisioning_client import (
    ComputeProvisioningClient,
    ComputeProvisioningError,
)
from compute_provisioning_contracts import (
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    HostCreate,
)
from compute_provisioning_service.main import app
from market_resource_pools_contracts import PoolCreate
from market_site.ledger import ALLOCATION_MODE_EXCLUSIVE
from market_site_client import SiteCapacityAdminClient, SiteCapacityClient

from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER

VM_POOL = "pool-deliverable-vm"
BARE_METAL_POOL = "pool-deliverable-bare-metal"
UNBACKED_POOL = "pool-deliverable-introductions"
VM_CLAIM = {"offering_mode": "vm", "gpu_count": 1}


class Site:
    """The service as a storefront and an operator reach it."""

    def __init__(self, provisioning, admin, site, compute) -> None:
        self.provisioning = provisioning
        self.admin = admin
        self.site = site
        self.compute = compute

    async def register_host(self, host_id: str) -> None:
        await self.provisioning.family.register_host(HostCreate(
            host_id=host_id,
            connection=ssh_connection(
                ssh_host="192.0.2.1", ssh_user="ubuntu", key_path="/keys/id"
            ),
        ))

    async def schedule(self, capacity_reservation_id: str, **constraint):
        return await self.compute.schedule_resource(FulfillmentScheduleRequest(
            capacity_reservation_id=capacity_reservation_id, market="vms", **constraint,
        ))

    async def declared(self) -> dict[str, dict]:
        return {row["resource_id"]: row for row in await self.admin.list_resources()}

    async def snapshot_ids(self) -> set[str]:
        return {row["resource_id"] for row in await self.site.snapshot()}

    async def bucketed(self, pool_id: str) -> int:
        projection = await self.site.capacity_bucket_projection()
        return sum(
            int(row["resource_count"])
            for row in projection["capacity_buckets"]
            if row["pool_id"] == pool_id
        )

    async def projected(self, pool_id: str) -> dict[str, dict]:
        projection = await self.site.resource_pool_projection()
        (pool,) = [
            row for row in projection["resource_pools"] if row["pool_id"] == pool_id
        ]
        return {entry["physical_resource_id"]: entry for entry in pool["resources"]}

    async def capacity_version(self) -> int:
        _, latest = await self.site.events_after(0)
        return latest


@pytest.fixture
async def service(client_and_queue):
    provisioning, _ = client_and_queue
    transport = ASGITransport(app=app)
    admin = SiteCapacityAdminClient(
        "http://test", STOREFRONT_SIGNER, SERVICE_AUTHORITIES, transport=transport,
    )
    site = SiteCapacityClient(
        "http://test", STOREFRONT_SIGNER, SERVICE_AUTHORITIES, transport=transport,
    )
    async with ComputeProvisioningClient(
        "http://test",
        signer=STOREFRONT_SIGNER,
        caller_role="seller",
        expected_authorities=SERVICE_AUTHORITIES,
        transport=transport,
    ) as compute:
        await provisioning.pools.create_pool(PoolCreate(
            id=VM_POOL, label=VM_POOL, provider="vm.ansible",
            policy_tags={
                "advertisable_modes": ["vm"],
                "capacity_backing": "backed",
                "deliverable_modes": ["vm"],
            },
            provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
        ))
        yield Site(provisioning, admin, site, compute)


async def test_a_disabled_hosts_declaration_is_neither_admitted_placed_nor_offered(
    service: Site,
):
    await service.register_host("kvm-deliverable")
    await service.admin.register_resource(
        "on-host", pool_id=VM_POOL, host_id="kvm-deliverable", total_units=4,
    )
    reserved = await service.site.reserve(claim=VM_CLAIM, deal_ref={})
    assert reserved is not None
    hold = reserved["capacity_reservation_id"]
    assert await service.bucketed(VM_POOL) == 1
    version = await service.capacity_version()

    await service.provisioning.family.disable_host("kvm-deliverable")

    # Admission answers no capacity, the ordinary way.
    assert await service.site.probe(claim=VM_CLAIM) is None
    assert await service.site.reserve(claim=VM_CLAIM, deal_ref={}) is None
    # Placement refuses the declaration before any executor is reached, even
    # for the hold admission placed on it before the disable.
    with pytest.raises(ComputeProvisioningError) as refused:
        await service.schedule(hold, resource_id="on-host")
    assert refused.value.status_code == 422
    assert "no_eligible_resource" in str(refused.value)
    # Every projection shows it not offered; the operator's listing keeps what
    # was declared; and the host's state recorded no capacity event.
    assert (await service.projected(VM_POOL))["on-host"]["enabled"] is False
    assert await service.bucketed(VM_POOL) == 0
    assert "on-host" not in await service.snapshot_ids()
    assert (await service.declared())["on-host"]["enabled"] is True
    assert await service.capacity_version() == version

    await service.provisioning.family.enable_host("kvm-deliverable")

    assert (await service.projected(VM_POOL))["on-host"]["enabled"] is True
    assert await service.bucketed(VM_POOL) == 1
    assert "on-host" in await service.snapshot_ids()
    assert await service.site.probe(claim=VM_CLAIM) is not None
    placed = await service.schedule(hold, resource_id="on-host")
    assert placed.settlement_resource_id == "on-host"
    assert await service.capacity_version() == version


async def test_a_bare_metal_view_reports_a_disabled_hosts_machine_unavailable(
    service: Site,
):
    await service.provisioning.pools.create_pool(PoolCreate(
        id=BARE_METAL_POOL, label=BARE_METAL_POOL, provider="bare_metal.ansible",
        policy_tags={
            "deliverable_modes": ["bare_metal"],
            "advertisable_modes": ["bare_metal"],
            "capacity_backing": "backed",
        },
        provider_config={},
    ))
    await service.register_host("bm-deliverable")
    await service.admin.register_resource(
        "machine", pool_id=BARE_METAL_POOL, host_id="bm-deliverable", total_units=1,
        attributes={
            "physical_host_id": "physical-deliverable",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
            "bare_metal_publication": {
                "enabled": True, "access_methods": ["ssh"], "capabilities": {},
            },
        },
    )

    def view(entries):
        return entries["machine"]["publication_views"]["bare_metal.v2"]

    assert view(await service.projected(BARE_METAL_POOL))["available"] is True

    await service.provisioning.family.disable_host("bm-deliverable")
    disabled = await service.projected(BARE_METAL_POOL)

    assert disabled["machine"]["enabled"] is False
    assert view(disabled)["available"] is False

    await service.provisioning.family.enable_host("bm-deliverable")

    assert view(await service.projected(BARE_METAL_POOL))["available"] is True


async def test_a_declaration_naming_an_unregistered_host_is_refused_and_not_offered(
    service: Site,
):
    await service.admin.register_resource(
        "unregistered", pool_id=VM_POOL, host_id="never-registered", total_units=4,
    )

    assert await service.site.probe(claim=VM_CLAIM) is None
    assert await service.site.reserve(claim=VM_CLAIM, deal_ref={}) is None
    assert (await service.projected(VM_POOL))["unregistered"]["enabled"] is False
    assert await service.bucketed(VM_POOL) == 0
    assert "unregistered" not in await service.snapshot_ids()
    assert (await service.declared())["unregistered"]["enabled"] is True

    # A hold on a usable declaration cannot be placed on the unregistered one.
    await service.register_host("kvm-usable")
    await service.admin.register_resource(
        "usable", pool_id=VM_POOL, host_id="kvm-usable", total_units=4,
    )
    hold = (await service.site.reserve(claim=VM_CLAIM, deal_ref={}))[
        "capacity_reservation_id"
    ]
    with pytest.raises(ComputeProvisioningError) as refused:
        await service.schedule(hold, resource_id="unregistered")
    assert refused.value.status_code == 422
    assert "no_eligible_resource" in str(refused.value)

    # Registering the host is what makes the declaration deliverable.
    await service.register_host("never-registered")

    assert (await service.projected(VM_POOL))["unregistered"]["enabled"] is True
    assert await service.bucketed(VM_POOL) >= 1
    assert "unregistered" in await service.snapshot_ids()
    placed = await service.schedule(hold, resource_id="unregistered")
    assert placed.settlement_resource_id == "unregistered"


async def test_an_unbacked_pools_declaration_keeps_its_own_enabled(service: Site):
    await service.provisioning.pools.create_pool(PoolCreate(
        id=UNBACKED_POOL, label=UNBACKED_POOL, provider="bare_metal.ansible",
        policy_tags={
            "deliverable_modes": [],
            "advertisable_modes": ["bare_metal"],
            "capacity_backing": "unbacked",
        },
        provider_config={},
    ))
    await service.register_host("bm-unbacked")
    await service.admin.register_resource(
        "introduction", pool_id=UNBACKED_POOL, host_id="bm-unbacked", total_units=1,
    )
    await service.provisioning.family.disable_host("bm-unbacked")

    assert (await service.projected(UNBACKED_POOL))["introduction"]["enabled"] is True


async def test_an_existing_assignment_keeps_its_disabled_host_and_waits_at_dispatch(
    service: Site, client_and_queue,
):
    await service.register_host("kvm-assigned")
    await service.admin.register_resource(
        "assigned", pool_id=VM_POOL, host_id="kvm-assigned", total_units=4,
    )
    reserved = await service.site.reserve(claim=VM_CLAIM, deal_ref={})
    capacity_reservation_id = reserved["capacity_reservation_id"]
    first = await service.schedule(capacity_reservation_id)

    await service.provisioning.family.disable_host("kvm-assigned")
    again = await service.schedule(capacity_reservation_id)

    assert again == first
    assert again.host_id == "kvm-assigned"

    begun = await service.compute.begin_fulfillment(FulfillmentRequestBody(
        capacity_reservation_id=capacity_reservation_id,
        market="vms",
        fulfillment_request={
            "kind": "vm.fulfillment.request",
            "schema_version": 1,
            "payload": {"ssh_pubkey": "ssh-ed25519 AAAA"},
        },
    ))

    # Job submission refuses a create against a disabled host, so no job is
    # recorded and the create waits to be retried.
    assert begun.state == "dispatch_pending"
    family = service.provisioning.family
    assert (await family.list_jobs()).total == 0

    # The host was the only obstacle: once it is enabled, one convergence
    # cycle submits the same create.
    await family.enable_host("kvm-assigned")
    _, job_queue = client_and_queue
    await family.pause_fulfillment_convergence()
    try:
        await family.advance_fulfillment_convergence_cycle()
    finally:
        await family.resume_fulfillment_convergence()
    await job_queue.wait_until_idle()

    assert (await family.list_jobs()).total == 1
