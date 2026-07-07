"""Integration tests for the bare-metal lease adapter.

The route is intentionally separate from the VM lease API even though this
transitional provisioner still lives under ``domains/vms``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import container as _container_module
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core_site.ledger import ALLOCATION_MODE_EXCLUSIVE
from main import app


def _future_dt(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


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
    reserved = _reserve_bare_metal("escrow-bm-api-1")

    lease = await bare_metal_client.register_lease(
        allocation_id=reserved["allocation_id"],
        escrow_uid="escrow-bm-api-1",
        machine_id="bm-node-1",
        physical_host_id="host-physical-1",
        access_ref={"ssh_user": "tenant-a"},
        lease_end_utc=_future_dt(),
        create_job_id="grant-ssh-1",
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
    assert allocation["vm_target"] is None


async def test_list_and_get_bare_metal_leases_exclude_vm_leases(
    bare_metal_client: BareMetalLeaseTestClient,
):
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
