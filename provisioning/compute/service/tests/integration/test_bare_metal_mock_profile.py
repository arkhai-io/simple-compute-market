"""Bare-metal access jobs under the provisioning mock profile.

Grant and reclaim run through the bare-metal adapter's own mock: the job
service's host check, inventory rendering, and result parsing are the real ones,
and the job's result carries the access fields the bare-metal fulfillment
provider reads. Rules installed through ``/test/bare-metal/mock-rules`` hold or
shape those jobs and never touch the VM mock.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from httpx import ASGITransport, AsyncClient
from market_site.ledger import ALLOCATION_MODE_EXCLUSIVE
from vm_provisioning_operator.models import HostCreate

from bare_metal_provisioning_adapter.services.bare_metal_mock_executor import (
    BareMetalMockAnsibleService,
)
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.main import app

HOST_ID = "bm-node-1"
SSH_HOST = "192.0.2.10"


@pytest.fixture
def bare_metal_runner():
    return BareMetalMockAnsibleService(MagicMock())


def _register_host() -> None:
    _container_module.resolved_host_service.register_host(
        HostCreate(
            host_id=HOST_ID,
            ssh_host=SSH_HOST,
            ssh_port=2201,
            ssh_user="root",
            ssh_key_type="path",
            ssh_key_value="/fake/id_ed25519",
            gpu_count=0,
        )
    )


def _reserve(escrow_uid: str) -> dict:
    ledger = _container_module.resolved_capacity_ledger_service
    ledger.register_resource(
        resource_id="bare-metal-node-1",
        total_units=1,
        host_id=HOST_ID,
        attributes={
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        pool_id="default",
    )
    reserved = ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": escrow_uid},
    )
    assert reserved is not None
    return reserved


async def _register_lease(reservation_id: str, escrow_uid: str) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/bare-metal/leases/",
            json={
                "capacity_reservation_id": reservation_id,
                "escrow_uid": escrow_uid,
                "host_id": HOST_ID,
                "physical_host_id": "host-physical-1",
                "access_ref": {
                    "ssh_user": "tenant-a",
                    "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
                },
                "lease_end_utc": (
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
            },
        )
    assert response.status_code < 400, response.text
    return response.json()


async def test_a_held_grant_runs_through_the_bare_metal_mock(test_client) -> None:
    _register_host()
    reserved = _reserve("escrow-bm-mock")
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-gate",
        match={"executor_action": NODE_GRANT_ACCESS_ACTION, "host_id": HOST_ID},
        pause_before_result=True,
    )

    preview = await test_client.evaluate_bare_metal_job(
        HOST_ID, action=NODE_GRANT_ACCESS_ACTION
    )
    assert preview["host_exists"] is True
    assert preview["rule_matched"] == "grant-gate"
    assert preview["would_pause"] is True

    await _register_lease(reserved["capacity_reservation_id"], "escrow-bm-mock")
    reservation = _container_module.resolved_capacity_ledger_service.get_reservation(
        reserved["capacity_reservation_id"]
    )
    grant_job_id = reservation["create_job_id"]

    await asyncio.sleep(0.05)
    rules = await test_client.list_bare_metal_mock_rules()
    assert rules[0]["rule_id"] == "grant-gate"
    assert rules[0]["paused"] is True
    assert await test_client.list_mock_rules() == []
    job = _container_module.resolved_job_service.get_job(grant_job_id)
    assert job.status not in {"succeeded", "failed"}

    await test_client.resume_bare_metal_rule("grant-gate")
    finished = await test_client.wait_for_job(grant_job_id, timeout=5.0)

    assert finished["status"] == "succeeded", finished
    access = finished["result"]["ansible_result"]
    assert access["action"] == NODE_GRANT_ACCESS_ACTION
    assert access["ssh_user"] == "tenant-a"
    assert access["host"] == SSH_HOST
    assert access["port"] == "2201"


async def test_a_bare_metal_rule_can_fail_a_grant(test_client) -> None:
    _register_host()
    reserved = _reserve("escrow-bm-mock-fail")
    await test_client.add_bare_metal_mock_rule(
        rule_id="grant-fails",
        match={"executor_action": NODE_GRANT_ACCESS_ACTION},
        fail_with="host unreachable",
    )

    await _register_lease(reserved["capacity_reservation_id"], "escrow-bm-mock-fail")
    reservation = _container_module.resolved_capacity_ledger_service.get_reservation(
        reserved["capacity_reservation_id"]
    )
    finished = await test_client.wait_for_job(reservation["create_job_id"], timeout=5.0)

    assert finished["status"] == "failed"
    assert "host unreachable" in finished["error"]


async def test_bare_metal_rule_routes_refuse_an_unknown_resume(test_client) -> None:
    from .conftest import AsyncProvisioningTestClientError

    with pytest.raises(AsyncProvisioningTestClientError) as refused:
        await test_client.resume_bare_metal_rule("missing")
    assert refused.value.status_code == 404
