"""Cross-service regression test for the opaque capacity boundary.

This test is owned by the storefront because it exercises the real
``RemoteCapacityClient`` implementation.  The repository-level test target runs
it in the compute-provisioning service environment and adds the storefront
implementation source to ``PYTHONPATH`` only for this test.  Neither production
package therefore gains a dependency on the other service implementation.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from market_resource_pools import PoolCreate

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.main import app
from core_storefront.capacity_remote import RemoteCapacityClient

_PLAYBOOK_PATH = "playbooks/vm-operations.yaml"
_PROVIDER_CONFIG = {"playbook_path": _PLAYBOOK_PATH, "extra_vars": {"region": "eu"}}


def _fulfillment_request(**overrides: Any) -> dict[str, Any]:
    payload = {
        "vm_target": "caller-value-is-not-placement",
        "vm_ram": 8192,
        "vm_vcpus": 4,
        "vm_disk_size": "80G",
        "vm_os_variant": "ubuntu22.04",
        "ssh_pubkey": "ssh-ed25519 AAAAtest",
    }
    payload.update(overrides)
    return {"kind": "vm.fulfillment.request", "schema_version": 1, "payload": payload}


@pytest.mark.asyncio
async def test_reserve_commit_schedule_begin_needs_no_placement_fields(
    client_and_queue,
) -> None:
    """The real capacity wire remains opaque through fulfillment acceptance."""
    pool_id = "pool-real-capacity-boundary"
    resource_pool_service = _container_module.resolved_resource_pool_service
    capacity_ledger_service = _container_module.resolved_capacity_ledger_service

    resource_pool_service.create_pool(
        PoolCreate(
            id=pool_id,
            label=pool_id,
            provider="ansible",
            provider_config=_PROVIDER_CONFIG,
        )
    )
    capacity_ledger_service.register_resource(
        resource_id=f"{pool_id}-r1",
        resource_type="compute.gpu",
        total_units=1,
        pool_id=pool_id,
        attributes={"vm_host": "kvm-real-boundary"},
        capacity={"gpu_count": 1, "vcpu_count": 4, "ram_gb": 8, "disk_gb": 80},
    )

    transport = ASGITransport(app=app)
    remote = RemoteCapacityClient("http://test", transport=transport)
    reservation = await remote.reserve(
        claim={"pool_id": pool_id, "gpu_count": 1},
        deal_ref={"agreement_id": "agreement-real-boundary", "market": "vms"},
    )
    assert reservation is not None
    assert {"resource_id", "capacity_bucket_id", "backing_resource_id"}.isdisjoint(
        reservation
    )

    capacity_reservation_id = reservation["capacity_reservation_id"]
    await remote.commit(
        resource_id=None,
        capacity_reservation_id=capacity_reservation_id,
        idempotency_ref="agreement-real-boundary",
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scheduled = await client.post(
            "/api/v1/fulfillment/schedule",
            json={
                "capacity_reservation_id": capacity_reservation_id,
                "market": "vms",
                "requirements": {},
                "resource_id": None,
            },
        )
        assert scheduled.status_code == 200, scheduled.text

        begun = await client.post(
            "/api/v1/fulfillment/begin",
            json={
                "capacity_reservation_id": capacity_reservation_id,
                "market": "vms",
                "fulfillment_request": _fulfillment_request(),
            },
        )
        assert begun.status_code == 200, begun.text
        assert begun.json()["capacity_reservation_id"] == capacity_reservation_id
        assert begun.json()["state"] == "dispatching"
