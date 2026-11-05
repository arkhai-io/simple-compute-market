"""Bare-metal relay fulfillment through the running application and typed clients.

All endpoints, tokens, and keys here are development fixtures, never for a public network.
The mock renderer supplies only a role fact; execution still resolves and signs the real lease.
"""

from __future__ import annotations

import asyncio

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from compute_provisioning.relays import Relay
from compute_provisioning_ansible import MockAnsibleRunner
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import AccessDelivery, LeaseTermination, RelayCreate
from market_resource_pools_contracts import PoolUpdate

from bare_metal_provisioning_adapter.services.mock_output import bare_metal_mock_output, shipped_output
from compute_provisioning_service import container as _container_module
from .bare_metal_deal import (
    HOST_ID, PHYSICAL_HOST_ID, POOL_ID, bare_metal_capacity, begin,
    committed_reservation, create_job_id, fulfillment_body, schedule,
)
from .test_bare_metal_mock_profile import _converge


def _relayed_output(playbook):
    if playbook.parameters["action"] != NODE_GRANT_ACCESS_ACTION:
        return bare_metal_mock_output(playbook)
    params = playbook.parameters
    fact = {
        "action": NODE_GRANT_ACCESS_ACTION, "host_id": HOST_ID,
        "physical_host_id": PHYSICAL_HOST_ID, "ssh_user": params["ssh_user"],
        "timestamp": "2030-01-01T00:00:01Z", "status": "success",
        "relay": {"enabled": True, "relay_addr": "203.0.113.9", "remote_port": params["remote_port"]},
    }
    return shipped_output(HOST_ID, "node_grant_access_data", fact)


@pytest.fixture
def bare_metal_runner():
    return MockAnsibleRunner(default_output=_relayed_output)


async def _scheduled_relay(clients):
    await clients.family.create_relay(RelayCreate(
        id="bare-metal-relay", relay_addr="203.0.113.9", relay_port=7000,
        vm_port_range_start=6100, vm_port_range_count=5, token="fixture-admission-token",
    ))
    await bare_metal_capacity(clients)
    await clients.pools.patch_pool(POOL_ID, PoolUpdate(provider_config={"relay_id": "bare-metal-relay"}))
    reservation = committed_reservation("escrow-bm-relay")
    await schedule(clients, reservation)
    return reservation


async def test_relayed_bare_metal_delivery_is_signed_redacted_and_releases_its_port(
    client_and_queue, test_client
):
    clients, queue = client_and_queue
    reservation = await _scheduled_relay(clients)
    validated = await clients.family.validate_fulfillment(
        fulfillment_body(reservation, "escrow-bm-relay")
    )
    assert validated.valid is True
    assert (await clients.family.list_relay_leases("bare-metal-relay")).leases == []
    fulfillment = await begin(clients, reservation, "escrow-bm-relay")
    assert await begin(clients, reservation, "escrow-bm-relay") == fulfillment
    job_id = create_job_id(reservation)
    finished = await test_client.wait_for_job(job_id, timeout=5)
    assert finished["status"] == "succeeded", finished
    params = (await clients.family.get_job(job_id)).params
    (lease,) = (await clients.family.list_relay_leases("bare-metal-relay")).leases
    assert lease.owner_id == reservation and lease.host_id == HOST_ID
    assert lease.grant_key_id is not None
    assert params["remote_port"] == lease.remote_port
    for read in [await clients.family.get_job(job_id), await clients.family.get_job_logs(job_id)]:
        serialized = read.model_dump_json()
        assert "fixture-admission-token" not in serialized
        assert "eyJhbGci" not in serialized
    assert params["relay_grant"] is None and params["relay_token"] is None
    await _converge(clients)
    result = await clients.family.get_fulfillment_result(fulfillment)
    delivery = AccessDelivery.model_validate(result.payload["domain_result"]["payload"])
    endpoint = delivery.endpoints[0]
    assert (endpoint.host, endpoint.port, endpoint.user) == ("203.0.113.9", lease.remote_port, params["ssh_user"])
    await clients.family.terminate_lease(reservation, LeaseTermination())
    await _converge(clients)
    await asyncio.wait_for(queue.wait_until_idle(), timeout=5)
    await _converge(clients)
    assert (await clients.family.get_fulfillment_status(fulfillment)).state == "torn_down"
    await clients.family.check_leases()
    (released,) = (await clients.family.list_relay_leases("bare-metal-relay")).leases
    assert released.released_at is not None
    assert (await clients.family.get_lease(reservation)).status == "released"


async def test_a_bare_metal_pool_with_no_active_relay_key_is_refused(client_and_queue):
    clients, _ = client_and_queue
    reservation = await _scheduled_relay(clients)
    # No route removes an active key. This establishes a pre-key stored relay.
    with _container_module.resolved_session_factory() as db, db.begin():
        relay = db.get(Relay, "bare-metal-relay")
        relay.grant_key_encrypted = relay.grant_key_id = relay.grant_key_public = None
    validation = await clients.family.validate_fulfillment(
        fulfillment_body(reservation, "escrow-bm-relay")
    )
    assert validation.valid is False
    assert "active grant key" in validation.model_dump()["issues"][0]["message"]
    with pytest.raises(ComputeProvisioningError) as refused:
        await begin(clients, reservation, "escrow-bm-relay")
    assert refused.value.status_code == 422
    assert (await clients.family.list_relay_leases("bare-metal-relay")).leases == []
