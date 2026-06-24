"""Capacity API: the full reserve→commit→release lifecycle over HTTP.

Exercises the /api/v1/capacity surface the storefront's remote
CapacityClient will speak — payload shapes here are the wire contract.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


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
        return resp.json()["allocation"]

    async def commit(
        self,
        allocation_id: str,
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
            f"/api/v1/capacity/allocations/{allocation_id}/commit",
            json=body,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["allocation"]

    async def release(self, **body: Any) -> dict | None:
        resp = await self._client.post("/api/v1/capacity/releases", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()["allocation"]

    async def truncate(self, allocation_id: str, lease_end_utc: str) -> dict | None:
        resp = await self._client.post(
            f"/api/v1/capacity/allocations/{allocation_id}/truncate-lease",
            json={"lease_end_utc": lease_end_utc},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["allocation"]

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
    assert await capacity.probe({"gpu_model": "H200"}) is not None
    assert await capacity.probe({"gpu_model": "A100"}) is None

    reserved = await capacity.reserve(
        {"gpu_count": 3}, {"listing_id": "lst-1", "escrow_uid": "0xesc"},
    )
    assert reserved["vm_host"] == "kvm1"
    assert reserved["available_gpu_count"] == 5
    assert (await capacity.snapshot())[0]["available_units"] == 5

    committed = await capacity.commit(
        reserved["allocation_id"],
        resource_id=reserved["resource_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01T01:00:00Z",
    )
    assert committed["state"] == "leased"

    truncated = await capacity.truncate(reserved["allocation_id"], "2026-06-01 00:00")
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
    assert all(set(e) <= {"version", "kind", "resource_id", "occurred_at"}
               for e in events)


@pytest.mark.asyncio
async def test_no_capacity_is_a_null_answer_not_an_error(capacity: CapacityApi):
    assert await capacity.reserve({"gpu_count": 1}, {}) is None
    assert await capacity.release(allocation_id="missing") is None


@pytest.mark.asyncio
async def test_register_lease_attaches_to_ledger_allocation(capacity: CapacityApi):
    """POST /leases records the lease tail on the allocation row — the
    leases surface is a view over the ledger."""
    import container as _container_module

    await capacity.register(
        "compute-kvm1-001", total_units=8, attributes={"vm_host": "kvm1"},
    )
    reserved = await capacity.reserve({"gpu_count": 1}, {"escrow_uid": "0xlease"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post("/api/v1/leases/", json={
            "resource_id": reserved["resource_id"],
            "allocation_id": reserved["allocation_id"],
            "escrow_uid": "0xlease",
            "vm_host": "kvm1",
            "vm_target": "tenant-led1",
            "lease_end_utc": "2099-01-01T00:00:00Z",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["id"] == reserved["allocation_id"]
        assert body["status"] == "active"

        listing = await http.get("/api/v1/leases/")
        assert listing.json()["total"] == 1
        assert listing.json()["leases"][0]["id"] == reserved["allocation_id"]

    ledger = _container_module.resolved_capacity_ledger_service
    row = ledger.get_allocation(reserved["allocation_id"])
    assert row["vm_target"] == "tenant-led1"
    assert row["state"] == "leased"
    assert row["lease_end_utc"] == "2099-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_register_lease_without_ledger_allocation_404s(
    capacity: CapacityApi,
):
    """Every reservation lives in the ledger; an unknown allocation means
    the hold lapsed or was already released — registration refuses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post("/api/v1/leases/", json={
            "resource_id": "compute-legacy-001",
            "allocation_id": "local-alloc-1",
            "escrow_uid": "0xlegacy",
            "vm_host": "kvm1",
            "vm_target": "tenant-leg1",
            "lease_end_utc": "2099-01-01T00:00:00Z",
        })
        assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_commit_unknown_allocation_404s(capacity: CapacityApi):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.post(
            "/api/v1/capacity/allocations/missing/commit",
            json={"resource_id": "r", "lease_end_utc": "2099-01-01 00:00"},
        )
        assert resp.status_code == 404
