"""Integration tests for the bare-metal lease adapter.

The route is intentionally separate from the VM lease API even though this
transitional provisioner still lives under ``domains/vms``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import container as _container_module
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from core_site.ledger import ALLOCATION_MODE_EXCLUSIVE
from db.models import AnsibleJob
from services.ansible_service import AnsibleResult
from services.async_job_queue import AsyncJobQueue
from provisioning_client.models import HostCreate
from main import app


GRANT_STDOUT = """\
PLAY [Grant bare-metal access] ***********************************************

TASK [debug] *****************************************************************
ok: [bm-node-1] => {
    "node_grant_access_data": {
        "action": "node_grant_access",
        "status": "granted",
        "host": "bm-node-1",
        "timestamp": "2026-01-01T00:00:00Z",
        "result_message": "access granted"
    }
}
"""


RECLAIM_STDOUT = """\
PLAY [Reclaim bare-metal access] *********************************************

TASK [debug] *****************************************************************
ok: [bm-node-1] => {
    "node_reclaim_access_data": {
        "action": "node_reclaim_access",
        "status": "reclaimed",
        "host": "bm-node-1",
        "timestamp": "2026-01-01T01:00:00Z",
        "result_message": "access reclaimed"
    }
}
"""


def _future_dt(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _ensure_bare_metal_host(name: str = "bm-node-1", *, enabled: bool = True) -> None:
    host_service = _container_module.resolved_host_service
    existing = host_service.get_host(name)
    if existing is None:
        host_service.register_host(
            HostCreate(
                name=name,
                kvm_host="192.0.2.10",
                ssh_user="root",
                ssh_key_type="path",
                ssh_key_value="/fake/id_ed25519",
                gpu_count=0,
                enabled=enabled,
            ),
        )
    elif enabled:
        host_service.enable_host(name)
    else:
        host_service.disable_host(name)


def _reserve_bare_metal(escrow_uid: str) -> dict:
    ledger = _container_module.resolved_capacity_ledger_service
    if "bare-metal-node-1" not in {
        r["resource_id"] for r in ledger.list_resources()
    }:
        ledger.register_resource(
            resource_id="bare-metal-node-1",
            total_units=1,
            attributes={
                "machine_id": "bm-node-1",
                "physical_host_id": "host-physical-1",
                "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
            },
        )
    reserved = ledger.reserve(
        claim={
            "physical_host_id": "host-physical-1",
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": escrow_uid},
    )
    assert reserved is not None
    return reserved


def _make_event_seam(job_queue: AsyncJobQueue) -> asyncio.Event:
    dispatched = asyncio.Event()
    original_callback = job_queue._on_job_started

    def _on_started(job_id: str) -> None:
        dispatched.set()
        if original_callback is not None:
            original_callback(job_id)

    job_queue._on_job_started = _on_started
    return dispatched


class BareMetalApiError(Exception):
    def __init__(self, method: str, path: str, status_code: int, body: str) -> None:
        self.status_code = status_code
        super().__init__(f"{method} {path} -> {status_code}: {body[:200]}")


class BareMetalLeaseTestClient:
    def __init__(self, transport: ASGITransport) -> None:
        self._client = AsyncClient(transport=transport, base_url="http://test")

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BareMetalLeaseTestClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def _get(self, path: str) -> dict | list:
        resp = await self._client.get(path)
        if resp.status_code >= 400:
            raise BareMetalApiError("GET", path, resp.status_code, resp.text)
        return resp.json()

    async def _post(self, path: str, body: dict) -> dict:
        resp = await self._client.post(path, json=body)
        if resp.status_code >= 400:
            raise BareMetalApiError("POST", path, resp.status_code, resp.text)
        return resp.json()

    async def register_lease(self, **body) -> dict:
        return await self._post("/api/v1/bare-metal/leases/", body)

    async def terminate_market_lease(self, allocation_id: str) -> dict:
        return await self._post(f"/api/v1/leases/{allocation_id}/terminate", {})

    async def list_leases(self) -> list[dict]:
        return await self._get("/api/v1/bare-metal/leases/")  # type: ignore[return-value]

    async def get_lease(self, allocation_id: str) -> dict:
        return await self._get(f"/api/v1/bare-metal/leases/{allocation_id}")  # type: ignore[return-value]

    async def get_lease_by_escrow(self, escrow_uid: str) -> dict:
        return await self._get(f"/api/v1/bare-metal/leases/by-escrow/{escrow_uid}")  # type: ignore[return-value]


@pytest_asyncio.fixture
async def bare_metal_client(client_and_queue):
    transport = ASGITransport(app=app)
    async with BareMetalLeaseTestClient(transport) as client:
        yield client


async def test_register_bare_metal_lease_uses_bare_metal_endpoint_and_view(
    bare_metal_client: BareMetalLeaseTestClient,
):
    _ensure_bare_metal_host()
    reserved = _reserve_bare_metal("escrow-bm-api-1")

    lease = await bare_metal_client.register_lease(
        allocation_id=reserved["allocation_id"],
        escrow_uid="escrow-bm-api-1",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        access_ref={"ssh_user": "tenant-a"},
        lease_end_utc=_future_dt(),
    )

    assert lease["allocation_id"] == reserved["allocation_id"]
    assert lease["escrow_uid"] == "escrow-bm-api-1"
    assert lease["machine_id"] == "bm-node-1"
    assert lease["physical_host_id"] == "host-physical-1"
    assert lease["state"] == "leased"
    assert lease["access_ref"] == {"ssh_user": "tenant-a"}

    ledger = _container_module.resolved_capacity_ledger_service
    allocation = ledger.get_allocation(lease["allocation_id"])
    assert allocation["executor_kind"] == "bare_metal"
    assert allocation["executor_target"] == "bm-node-1"
    assert allocation["executor_ref"] == {
        "physical_host_id": "host-physical-1",
        "ssh_user": "tenant-a",
    }
    assert allocation["create_job_id"]
    assert allocation["vm_target"] is None

    session_factory = _container_module.resolved_session_factory
    with session_factory() as db:
        job = db.get(AnsibleJob, allocation["create_job_id"])
        assert job is not None
        assert job.params["vm_action"] == NODE_GRANT_ACCESS_ACTION
        assert job.params["vm_host"] == "bm-node-1"
        assert job.params["executor_kind"] == "bare_metal"
        assert job.params["executor_action"] == NODE_GRANT_ACCESS_ACTION
        assert job.params["executor_target"] == "bm-node-1"
        assert job.params["physical_host_id"] == "host-physical-1"


async def test_list_and_get_bare_metal_leases_exclude_vm_leases(
    bare_metal_client: BareMetalLeaseTestClient,
):
    _ensure_bare_metal_host()
    reserved = _reserve_bare_metal("escrow-bm-api-2")
    lease = await bare_metal_client.register_lease(
        allocation_id=reserved["allocation_id"],
        escrow_uid="escrow-bm-api-2",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        lease_end_utc=_future_dt(),
    )

    leases = await bare_metal_client.list_leases()
    assert [item["escrow_uid"] for item in leases] == ["escrow-bm-api-2"]
    assert await bare_metal_client.get_lease(lease["allocation_id"]) == lease
    assert await bare_metal_client.get_lease_by_escrow("escrow-bm-api-2") == lease


async def test_unknown_bare_metal_lease_returns_404(
    bare_metal_client: BareMetalLeaseTestClient,
):
    with pytest.raises(BareMetalApiError) as exc_info:
        await bare_metal_client.get_lease("missing")

    assert exc_info.value.status_code == 404


async def test_generic_market_lease_terminate_dispatches_bare_metal_reclaim(
    bare_metal_client: BareMetalLeaseTestClient,
):
    _ensure_bare_metal_host()
    reserved = _reserve_bare_metal("escrow-bm-api-reclaim")
    lease = await bare_metal_client.register_lease(
        allocation_id=reserved["allocation_id"],
        escrow_uid="escrow-bm-api-reclaim",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        access_ref={"ssh_user": "tenant-a"},
        lease_end_utc=_future_dt(),
    )

    terminated = await bare_metal_client.terminate_market_lease(
        lease["allocation_id"],
    )

    assert terminated["id"] == lease["allocation_id"]
    assert terminated["status"] == "releasing"

    ledger = _container_module.resolved_capacity_ledger_service
    allocation = ledger.get_allocation(lease["allocation_id"])
    assert allocation["state"] == "releasing"
    assert allocation["executor_kind"] == "bare_metal"
    assert allocation["release_job_id"]
    assert allocation["vm_remove_job_id"] is None

    session_factory = _container_module.resolved_session_factory
    with session_factory() as db:
        job = db.get(AnsibleJob, allocation["release_job_id"])
        assert job is not None
        assert job.params["vm_action"] == NODE_RECLAIM_ACCESS_ACTION
        assert job.params["vm_host"] == "bm-node-1"
        assert job.params["executor_kind"] == "bare_metal"
        assert job.params["executor_action"] == NODE_RECLAIM_ACCESS_ACTION
        assert job.params["executor_target"] == "bm-node-1"
        assert job.params["bare_metal_reclaim_policy"] == "remove_lease_key"


async def test_bare_metal_grant_and_reclaim_jobs_succeed_with_executor_playbook(
    client_and_queue,
    fake_ansible,
):
    provisioning_client, job_queue = client_and_queue
    async with BareMetalLeaseTestClient(ASGITransport(app=app)) as bare_metal_client:
        _ensure_bare_metal_host()
        reserved = _reserve_bare_metal("escrow-bm-api-smoke")
        fake_ansible.wait_for_playbook.side_effect = [
            AnsibleResult(stdout=GRANT_STDOUT, stderr="", process_id=99999),
            AnsibleResult(stdout=RECLAIM_STDOUT, stderr="", process_id=99999),
        ]

        grant_dispatched = _make_event_seam(job_queue)
        lease = await bare_metal_client.register_lease(
            allocation_id=reserved["allocation_id"],
            escrow_uid="escrow-bm-api-smoke",
            machine_id="bm-node-1",
            physical_host_id="host-physical-1",
            access_ref={
                "ssh_user": "tenant-a",
                "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
            },
            lease_end_utc=_future_dt(),
        )
        ledger = _container_module.resolved_capacity_ledger_service
        allocation = ledger.get_allocation(lease["allocation_id"])
        grant_job_id = allocation["create_job_id"]
        await asyncio.wait_for(grant_dispatched.wait(), timeout=5.0)
        grant_job = await provisioning_client.poll_until_complete(
            grant_job_id,
            timeout=5.0,
            poll_interval=0.05,
        )

        assert grant_job.status == "succeeded"
        assert grant_job.result["action"] == NODE_GRANT_ACCESS_ACTION
        assert grant_job.result["status"] == "granted"
        assert grant_job.result["host"] == "bm-node-1"
        first_playbook = fake_ansible.start_playbook.call_args_list[0].kwargs
        assert first_playbook["playbook_path"].name == "bare-metal-node-access.yml"
        assert first_playbook["limit"] == "bm-node-1"

        reclaim_dispatched = _make_event_seam(job_queue)
        terminated = await bare_metal_client.terminate_market_lease(
            lease["allocation_id"],
        )
        allocation = ledger.get_allocation(lease["allocation_id"])
        release_job_id = allocation["release_job_id"]
        await asyncio.wait_for(reclaim_dispatched.wait(), timeout=5.0)
        reclaim_job = await provisioning_client.poll_until_complete(
            release_job_id,
            timeout=5.0,
            poll_interval=0.05,
        )

        assert reclaim_job.status == "succeeded"
        assert reclaim_job.result["action"] == NODE_RECLAIM_ACCESS_ACTION
        assert reclaim_job.result["status"] == "reclaimed"
        assert reclaim_job.result["host"] == "bm-node-1"
        second_playbook = fake_ansible.start_playbook.call_args_list[1].kwargs
        assert second_playbook["playbook_path"].name == "bare-metal-node-access.yml"
        assert second_playbook["limit"] == "bm-node-1"

        allocation = ledger.get_allocation(lease["allocation_id"])
        assert allocation["state"] == "releasing"
        assert allocation["create_job_id"] == grant_job_id
        assert allocation["release_job_id"] == release_job_id


async def test_register_bare_metal_lease_for_unknown_machine_does_not_queue_job(
    bare_metal_client: BareMetalLeaseTestClient,
):
    reserved = _reserve_bare_metal("escrow-bm-api-unknown")
    session_factory = _container_module.resolved_session_factory
    with session_factory() as db:
        job_count_before = db.query(AnsibleJob).count()

    with pytest.raises(BareMetalApiError) as exc_info:
        await bare_metal_client.register_lease(
            allocation_id=reserved["allocation_id"],
            escrow_uid="escrow-bm-api-unknown",
            machine_id="missing-bm-node",
            physical_host_id="host-physical-1",
            lease_end_utc=_future_dt(),
        )

    assert exc_info.value.status_code == 404
    with session_factory() as db:
        assert db.query(AnsibleJob).count() == job_count_before
