"""Disabling a relay drains it, across the running service.

A disabled relay takes no new delivery: its pools' hosts leave the hosts taking
new delivery, so no claim is admitted against, placed on, or projected enabled
for their declarations, and acceptance leases no port on it. The deliveries it
already carries run to their end: a VM guest's teardown and a bare-metal
grant's reclaim run on it and release their ports, and the relay then reads
drained. Enabled again before it drains, it takes new delivery as before.

Every step a route serves goes through the canonical typed clients: relays,
hosts, pools, scheduling, fulfillment, and leases through the family client;
declarations, admission, and projections through the site clients. The
bare-metal declaration and reservation, which a site's operator and a
storefront make at the site, are made on the composed ledger, as the
bare-metal suites make them. Only the Ansible runs are doubled. Public
addresses are documentation-range placeholders and guest addresses private
ones, none connected to, and the token is a development fixture.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport

from compute_provisioning_ansible import MockAnsibleRunner, ssh_connection
from compute_provisioning_ansible.runner import AnsibleResult
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import (
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    HostCreate,
    LeaseTermination,
    RelayCreate,
)
from compute_provisioning_service.main import app
from market_resource_pools_contracts import PoolCreate, PoolUpdate
from market_site_client import SiteCapacityAdminClient, SiteCapacityClient
from vm_provisioning_adapter.codec import VM_RESULT_FACTS
from vm_provisioning_adapter.guest_names import fulfillment_guest_name
from vm_provisioning_adapter.services.mock_output import shipped_output, tenant_account

from .bare_metal_deal import (
    POOL_ID as BARE_METAL_POOL,
    bare_metal_capacity,
    begin as begin_bare_metal,
    committed_reservation,
    schedule as schedule_bare_metal,
)
from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER
from .test_bare_metal_relay import _relayed_output

RELAY = "drain-relay"
# The address the bare-metal grant's mocked run reports its relay at.
RELAY_ADDR = "203.0.113.9"
VM_POOL = "pool-drain-vm"
VM_HOST = "kvm-drain"
VM_RESOURCE = "vm-on-the-relay"
VM_CLAIM = {"offering_mode": "vm", "gpu_count": 1}


@pytest.fixture
def bare_metal_runner():
    """Bare-metal runs report the relay their grant was leased on."""
    return MockAnsibleRunner(default_output=_relayed_output)


class Site:
    """The service as an operator and a storefront reach it."""

    def __init__(self, clients, queue, admin, site) -> None:
        self.clients = clients
        self.family = clients.family
        self.queue = queue
        self.admin = admin
        self.site = site

    async def converge(self, records: int = 1) -> None:
        """A convergence cycle per record. The timer-driven loop is held for
        the whole test, so no cycle runs but the ones a test steps, and the
        harness's settings bound a cycle's batch to one record of each state."""
        for _ in range(records):
            await self.family.advance_fulfillment_convergence_cycle()

    async def settle(self, records: int) -> None:
        """Dispatch what convergence owes, run it, then converge on its outcome."""
        await self.converge(records)
        await asyncio.wait_for(self.queue.wait_until_idle(), timeout=5)
        await self.converge(records)

    async def relay_with_a_vm_pool(self) -> None:
        """The relay, a VM pool on it, the pool's host, and its declaration."""
        await self.family.create_relay(RelayCreate(
            id=RELAY, relay_addr=RELAY_ADDR, relay_port=7000,
            vm_port_range_start=6100, vm_port_range_count=10,
            token="fixture-admission-token",
        ))
        await self.clients.pools.create_pool(PoolCreate(
            id=VM_POOL, label=VM_POOL, provider="vm.ansible",
            policy_tags={
                "advertisable_modes": ["vm"],
                "capacity_backing": "backed",
                "deliverable_modes": ["vm"],
            },
            provider_config={"playbook_path": "playbooks/vm-operations.yaml", "relay_id": RELAY},
        ))
        await self.family.register_host(HostCreate(
            host_id=VM_HOST,
            connection=ssh_connection(ssh_host="192.0.2.40", key_path="/keys/id"),
            pool_id=VM_POOL,
        ))
        await self.admin.register_resource(
            VM_RESOURCE, pool_id=VM_POOL, host_id=VM_HOST, total_units=4,
        )

    async def vm_hold(self) -> str:
        """A committed VM reservation on the declaration, with a lease end."""
        reserved = await self.site.reserve(claim=VM_CLAIM, deal_ref={})
        assert reserved is not None, "the VM declaration could not be reserved"
        start = datetime.now(timezone.utc)
        await self.site.commit(
            capacity_reservation_id=reserved["capacity_reservation_id"],
            lease_start_utc=start.isoformat(),
            lease_end_utc=(start + timedelta(hours=2)).isoformat(),
        )
        return reserved["capacity_reservation_id"]

    async def schedule_vm(self, capacity_reservation_id: str):
        return await self.family.schedule_resource(FulfillmentScheduleRequest(
            capacity_reservation_id=capacity_reservation_id, market="vms",
        ))

    @staticmethod
    def vm_request(capacity_reservation_id: str) -> FulfillmentRequestBody:
        return FulfillmentRequestBody(
            capacity_reservation_id=capacity_reservation_id,
            market="vms",
            fulfillment_request={
                "kind": "vm.fulfillment.request",
                "schema_version": 1,
                "payload": {"ssh_pubkey": "ssh-ed25519 AAAA buyer"},
            },
        )

    async def begin_vm(self, capacity_reservation_id: str) -> str:
        accepted = await self.family.begin_fulfillment(
            self.vm_request(capacity_reservation_id)
        )
        return accepted.fulfillment_id

    async def held(self) -> dict[str, int]:
        """The relay's unreleased leases, by owner."""
        return {
            lease.owner_id: lease.remote_port
            for lease in (await self.family.list_relay_leases(RELAY)).leases
            if lease.released_at is None
        }

    async def projected(self, pool_id: str, resource_id: str) -> bool:
        projection = await self.site.resource_pool_projection()
        (pool,) = [row for row in projection["resource_pools"] if row["pool_id"] == pool_id]
        (entry,) = [
            row for row in pool["resources"] if row["physical_resource_id"] == resource_id
        ]
        return entry["enabled"]


@pytest.fixture
async def service(client_and_queue):
    clients, queue = client_and_queue
    transport = ASGITransport(app=app)
    admin = SiteCapacityAdminClient(
        "http://test", STOREFRONT_SIGNER, SERVICE_AUTHORITIES, transport=transport,
    )
    site = SiteCapacityClient(
        "http://test", STOREFRONT_SIGNER, SERVICE_AUTHORITIES, transport=transport,
    )
    # Held from the start: a timer cycle between two stepped ones would claim
    # a record and leave the next stepped cycle nothing to advance. A cycle
    # already running when the pause lands finishes first, so the pause is
    # repeated, a bounded number of times, until the loop answers at its gate.
    for _ in range(50):
        if (await clients.family.pause_fulfillment_convergence()).at_gate:
            break
    else:
        raise AssertionError("the fulfillment convergence loop never reached its gate")
    try:
        yield Site(clients, queue, admin, site)
    finally:
        await clients.family.resume_fulfillment_convergence()


def _relayed_create(capacity_reservation_id: str, port: int) -> AnsibleResult:
    """A successful create of the reservation's guest, reached through the
    relay at its leased port, as the VM role prints it."""
    guest = fulfillment_guest_name(capacity_reservation_id)
    user = tenant_account(guest)
    access = f"ssh -p {port} {user}@{RELAY_ADDR}"
    fact = {
        "action": "create",
        "vm_name": guest,
        "timestamp": "2030-01-01T00:00:01Z",
        "host": VM_HOST,
        "status": "success",
        "vm_state": "running",
        "vm_ip_internal": "192.168.122.2",
        "external_ssh_port": "N/A - Using FRP",
        "tenant_user": user,
        "authentication": {
            "root": {
                "password": "fixture-root",
                "ssh_key_path_host": f"~/.ssh/{guest}_root_ed25519",
                "ssh_commands": {"internal": "ssh root@192.168.122.2"},
            },
            "tenant": {
                "password": "fixture-tenant",
                "key_type": "provided",
                "public_key": "ssh-ed25519 AAAA buyer",
                "ssh_commands": {
                    "internal": f"ssh -i <your_private_key> {user}@192.168.122.2",
                    "external": f"ssh -i <your_private_key> -p {port} {user}@{RELAY_ADDR}",
                },
            },
        },
        "relay": {
            "enabled": True,
            "relay_addr": RELAY_ADDR,
            "remote_port": str(port),
            "ssh_access": access,
        },
    }
    return AnsibleResult(
        stdout=shipped_output(VM_HOST, VM_RESULT_FACTS["create"], fact), stderr="", process_id=1
    )


def _removed(capacity_reservation_id: str) -> AnsibleResult:
    """A successful removal of the reservation's guest and its proxy."""
    fact = {
        "action": "vm_remove",
        "vm_name": fulfillment_guest_name(capacity_reservation_id),
        "timestamp": "2030-01-01T00:00:02Z",
        "host": VM_HOST,
        "status": "success",
        "cleanup_record": True,
        "guest_present": True,
        "destroy_output": "",
        "cleanup_output": [],
        "error": "",
    }
    return AnsibleResult(
        stdout=shipped_output(VM_HOST, VM_RESULT_FACTS["vm_remove"], fact), stderr="", process_id=2
    )


async def test_a_disabled_relay_takes_no_new_delivery_and_its_leases_drain(
    service: Site, fake_ansible,
):
    """Scenario "A relay is disabled while it carries deliveries"."""
    await service.relay_with_a_vm_pool()
    vm = await service.vm_hold()
    # The VM begins first on a fresh window, so its lease is the window's first port.
    fake_ansible.wait_for_playbook.side_effect = [_relayed_create(vm, 6100), _removed(vm)]
    await service.schedule_vm(vm)
    vm_fulfillment = await service.begin_vm(vm)
    await bare_metal_capacity(service.clients)
    await service.clients.pools.patch_pool(
        BARE_METAL_POOL, PoolUpdate(provider_config={"relay_id": RELAY})
    )
    bare_metal = committed_reservation("escrow-drain-bm")
    await schedule_bare_metal(service.clients, bare_metal)
    bare_metal_fulfillment = await begin_bare_metal(
        service.clients, bare_metal, "escrow-drain-bm"
    )
    await asyncio.wait_for(service.queue.wait_until_idle(), timeout=5)
    await service.converge(records=2)
    for fulfillment in (vm_fulfillment, bare_metal_fulfillment):
        assert (await service.family.get_fulfillment_status(fulfillment)).state == "active"
    assert await service.held() == {vm: 6100, bare_metal: 6101}
    # A second hold on the VM declaration, made while the relay took delivery,
    # and the declaration still has capacity for a third.
    waiting = await service.vm_hold()
    pinned = {**VM_CLAIM, "resource_id": VM_RESOURCE}
    assert await service.site.probe(claim=pinned) is not None

    disabled = await service.family.set_relay_enabled(RELAY, False)

    assert (disabled.active_lease_count, disabled.drained) == (2, False)
    # Admission answers no capacity on the declaration, placement refuses it
    # even for the hold made before the disable, and the projections show both
    # pools' declarations not enabled.
    assert await service.site.probe(claim=pinned) is None
    with pytest.raises(ComputeProvisioningError) as refused:
        await service.schedule_vm(waiting)
    assert refused.value.status_code == 422
    assert "no_eligible_resource" in str(refused.value)
    assert await service.projected(VM_POOL, VM_RESOURCE) is False
    assert await service.projected(BARE_METAL_POOL, "bare-metal-node-1") is False

    # The deliveries it carries end as their leases end: the guest's teardown
    # and the grant's reclaim run on the disabled relay.
    await service.family.terminate_lease(vm, LeaseTermination())
    await service.family.terminate_lease(bare_metal, LeaseTermination())
    await service.settle(records=2)
    for fulfillment in (vm_fulfillment, bare_metal_fulfillment):
        assert (await service.family.get_fulfillment_status(fulfillment)).state == "torn_down"
    assert (await service.family.get_relay(RELAY)).drained is False

    await service.family.check_leases()

    assert await service.held() == {}
    drained = await service.family.get_relay(RELAY)
    assert (drained.active_lease_count, drained.drained) == (0, True)


async def test_acceptance_on_a_pool_whose_relay_is_disabled_leases_no_port(service: Site):
    """Scenario "A claim reaches fulfillment on a disabled relay": a claim
    placed before the disable reaches acceptance, which refuses before leasing
    a port. Validation, the surface that reports why, names the relay;
    acceptance answers the refusal's code alone."""
    await service.relay_with_a_vm_pool()
    vm = await service.vm_hold()
    await service.schedule_vm(vm)

    await service.family.set_relay_enabled(RELAY, False)

    validated = await service.family.validate_fulfillment(service.vm_request(vm))
    assert validated.valid is False
    (issue,) = validated.model_dump()["issues"]
    assert f"'{RELAY}'" in issue["message"]
    with pytest.raises(ComputeProvisioningError) as refused:
        await service.begin_vm(vm)
    assert refused.value.status_code == 422
    assert "provider_config_invalid" in str(refused.value)
    assert (await service.family.list_relay_leases(RELAY)).leases == []


async def test_a_relay_enabled_again_before_it_drains_takes_new_delivery(
    service: Site, fake_ansible,
):
    """Scenario "A relay disabled by mistake is enabled again before it drains"."""
    await service.relay_with_a_vm_pool()
    first, second = await service.vm_hold(), await service.vm_hold()
    fake_ansible.wait_for_playbook.side_effect = [
        _relayed_create(first, 6100),
        _relayed_create(second, 6101),
    ]
    await service.schedule_vm(first)
    delivered = await service.begin_vm(first)
    await asyncio.wait_for(service.queue.wait_until_idle(), timeout=5)
    await service.converge()
    assert (await service.family.get_fulfillment_status(delivered)).state == "active"

    await service.family.set_relay_enabled(RELAY, False)
    assert await service.projected(VM_POOL, VM_RESOURCE) is False
    enabled = await service.family.set_relay_enabled(RELAY, True)

    assert (enabled.active_lease_count, enabled.drained) == (1, False)
    assert await service.projected(VM_POOL, VM_RESOURCE) is True
    assert await service.site.probe(claim=VM_CLAIM) is not None
    # Allocation resumes: the second claim is placed and leased a port.
    await service.schedule_vm(second)
    await service.begin_vm(second)
    await asyncio.wait_for(service.queue.wait_until_idle(), timeout=5)
    assert await service.held() == {first: 6100, second: 6101}
    # The delivery the relay carried through the disable was never touched.
    await service.converge()
    assert (await service.family.get_fulfillment_status(delivered)).state == "active"
