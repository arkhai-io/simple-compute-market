"""The host requirement across the deployed provisioning surface.

The Ansible provider delivers through a host, so the running service refuses to
place capacity whose declaration names none. Every step here goes through the
canonical typed clients: pools through ``ProvisioningClient``, declarations
through ``SiteCapacityAdminClient``, reservations through ``SiteCapacityClient``,
and scheduling and acceptance through ``ComputeProvisioningClient``, so a route
or body change breaks these tests through the clients.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport

from compute_provisioning import (
    ComputeProvisioningClient,
    ComputeProvisioningError,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    PoolCreate,
)
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.main import app
from market_fulfillment import (
    SettlementRecord,
    SettlementRepository,
    SettlementRequirement,
    SettlementResource,
)
from market_site_client import SiteCapacityAdminClient, SiteCapacityClient

from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER

POOL = "pool-host-requirement"
VM_CLAIM = {"offering_mode": "vm", "gpu_count": 1}


@pytest.fixture
async def clients(client_and_queue):
    provisioning_client, _ = client_and_queue
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
        await provisioning_client.create_pool(PoolCreate(
            id=POOL, label=POOL, provider="ansible",
            policy_tags={"advertisable_modes": ["vm"], "capacity_backing": "backed", "deliverable_modes": ["vm"]},
            provider_config={"playbook_path": "playbooks/vm-operations.yaml"},
        ))
        await admin.register_resource(
            "hosted", pool_id=POOL, host_id="kvm-host-requirement", total_units=4,
        )
        yield admin, site, compute


async def _schedule(compute, capacity_reservation_id, **constraint):
    return await compute.schedule_resource(FulfillmentScheduleRequest(
        capacity_reservation_id=capacity_reservation_id, market="vms", **constraint,
    ))


async def test_placing_a_declaration_naming_no_host_is_refused_before_any_effect(
    clients, fake_ansible,
):
    admin, site, compute = clients
    await admin.register_resource("no-host", pool_id=POOL, total_units=4)
    reserved = await site.reserve(claim=VM_CLAIM, deal_ref={})
    capacity_reservation_id = reserved["capacity_reservation_id"]

    with pytest.raises(ComputeProvisioningError) as refused:
        await _schedule(compute, capacity_reservation_id, resource_id="no-host")
    assert refused.value.status_code == 422

    # Nothing was assigned, so there is nothing to accept...
    with pytest.raises(ComputeProvisioningError) as not_scheduled:
        await compute.begin_fulfillment(FulfillmentRequestBody(
            capacity_reservation_id=capacity_reservation_id,
            market="vms",
            fulfillment_request={
                "kind": "vm.fulfillment.request",
                "schema_version": 1,
                "payload": {"vm_target": "vm-host-requirement"},
            },
        ))
    assert not_scheduled.value.status_code == 404
    # ...no execution was reached, and the hold stayed where admission put it.
    fake_ansible.start_playbook.assert_not_called()
    available = {
        row["resource_id"]: row["available_units"] for row in await site.snapshot()
    }
    assert available == {"hosted": 3, "no-host": 4}


async def test_an_assignment_recorded_with_no_host_is_refused_rather_than_returned(
    clients,
):
    """An assignment an earlier scheduler placed on a declaration naming no
    host. No public API can create one now, so the row is seeded directly."""
    admin, site, compute = clients
    await admin.register_resource("no-host", pool_id=POOL, total_units=4)
    reserved = await site.reserve(claim=VM_CLAIM, deal_ref={})
    capacity_reservation_id = reserved["capacity_reservation_id"]
    session_factory = _container_module.resolved_session_factory
    with session_factory() as db, db.begin():
        SettlementRepository().schedule(
            db,
            capacity_reservation_id=capacity_reservation_id,
            market="vms",
            scheduling_requirements=SettlementRequirement(
                offering_mode="vm",
                resource_kind="compute.gpu",
                dimensions={"gpu_count": 1},
                attributes={},
            ),
            resource=SettlementResource(
                settlement_resource_id="no-host",
                pool_id=POOL,
                offering_mode="vm",
                resource_kind="compute.gpu",
                provider="ansible",
                attributes={},
                host_id=None,
            ),
        )

    with pytest.raises(ComputeProvisioningError) as refused:
        await _schedule(compute, capacity_reservation_id)
    assert refused.value.status_code == 422

    with session_factory() as db:
        assert db.get(SettlementRecord, capacity_reservation_id).state == "assigned"
