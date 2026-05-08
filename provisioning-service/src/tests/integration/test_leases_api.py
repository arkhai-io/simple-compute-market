"""Integration tests for the VM leases API.

All calls go through ProvisioningClient methods — no route strings in test code.

Coverage:
  - POST /api/v1/leases: create round-trips through client
  - GET /api/v1/leases: list with filters
  - GET /api/v1/leases/{id}: get by id
  - GET /api/v1/leases/by-escrow/{uid}: get by escrow UID
  - PATCH /api/v1/leases/{id}: partial update
  - DELETE /api/v1/leases/{id}/cancel: cancel
  - POST /api/v1/system/check-leases: triggers immediate watchdog cycle

What is NOT covered here (unit test jurisdiction):
  - LeaseService transition logic
  - LeaseCheckService grace period and force logic
  - _patch_storefront_resource HTTP interactions
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from client.provisioning_client import ProvisioningClient, ProvisioningError


def _future_dt(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_dt(seconds: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


_SAMPLE_LEASE = {
    "resource_id": "compute-ww1-001",
    "escrow_uid": "escrow-integ-001",
    "vm_host": "ww1",
    "vm_target": "tenant-a1b2",
}


async def _create(client: ProvisioningClient, *, hours: int = 2, escrow_uid: str = "escrow-integ-001", **overrides) -> dict:
    body = {**_SAMPLE_LEASE, "escrow_uid": escrow_uid, "lease_end_utc": _future_dt(hours=hours), **overrides}
    return await client.register_lease(**body)


class TestCreateLease:
    async def test_create_returns_lease_data(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _create(client)
        assert lease["resource_id"] == "compute-ww1-001"
        assert lease["escrow_uid"] == "escrow-integ-001"
        assert lease["vm_host"] == "ww1"
        assert lease["status"] in ("active", "pending")
        assert "id" in lease

    async def test_create_status_active_when_no_start(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _create(client)
        assert lease["status"] == "active"

    async def test_create_conflict_on_duplicate_escrow(self, client_and_queue):
        client, _ = client_and_queue
        await _create(client, escrow_uid="esc-dup")
        with pytest.raises(ProvisioningError) as exc_info:
            await _create(client, escrow_uid="esc-dup")
        assert exc_info.value.status_code == 409


class TestListLeases:
    async def test_empty_returns_empty_list(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.list_leases()
        assert result["leases"] == []
        assert result["total"] == 0

    async def test_lists_created_leases(self, client_and_queue):
        client, _ = client_and_queue
        await _create(client, escrow_uid="e1")
        await _create(client, escrow_uid="e2")
        result = await client.list_leases()
        assert result["total"] == 2

    async def test_filter_by_status(self, client_and_queue):
        client, _ = client_and_queue
        await _create(client, escrow_uid="ef1")
        result = await client.list_leases(status="active")
        assert all(l["status"] == "active" for l in result["leases"])

    async def test_filter_by_escrow_uid(self, client_and_queue):
        client, _ = client_and_queue
        await _create(client, escrow_uid="filter-target")
        await _create(client, escrow_uid="filter-other")
        result = await client.list_leases(escrow_uid="filter-target")
        assert result["total"] == 1
        assert result["leases"][0]["escrow_uid"] == "filter-target"


class TestGetLease:
    async def test_get_by_id(self, client_and_queue):
        client, _ = client_and_queue
        created = await _create(client, escrow_uid="e-get")
        fetched = await client.get_lease(created["id"])
        assert fetched["id"] == created["id"]
        assert fetched["escrow_uid"] == "e-get"

    async def test_get_nonexistent_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_lease("nonexistent-id")
        assert exc_info.value.status_code == 404

    async def test_get_by_escrow(self, client_and_queue):
        client, _ = client_and_queue
        await _create(client, escrow_uid="e-by-escrow")
        fetched = await client.get_lease_by_escrow("e-by-escrow")
        assert fetched["escrow_uid"] == "e-by-escrow"

    async def test_get_by_escrow_nonexistent_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_lease_by_escrow("no-such-escrow")
        assert exc_info.value.status_code == 404


class TestUpdateLease:
    async def test_update_status(self, client_and_queue):
        client, _ = client_and_queue
        created = await _create(client, escrow_uid="e-update")
        updated = await client.update_lease(created["id"], status="cancelled")
        assert updated["status"] == "cancelled"

    async def test_update_check_job_id(self, client_and_queue):
        client, _ = client_and_queue
        created = await _create(client, escrow_uid="e-cjid")
        updated = await client.update_lease(created["id"], check_job_id="job-xyz")
        assert updated["check_job_id"] == "job-xyz"

    async def test_update_nonexistent_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.update_lease("no-such-id", status="cancelled")
        assert exc_info.value.status_code == 404


class TestCancelLease:
    async def test_cancel_transitions_to_cancelled(self, client_and_queue):
        client, _ = client_and_queue
        created = await _create(client, escrow_uid="e-cancel")
        cancelled = await client.cancel_lease(created["id"])
        assert cancelled["status"] == "cancelled"

    async def test_cancel_nonexistent_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.cancel_lease("no-such-id")
        assert exc_info.value.status_code == 404


class TestCheckLeasesEndpoint:
    async def test_check_leases_returns_summary(self, client_and_queue):
        """POST /api/v1/system/check-leases returns the summary dict."""
        from httpx import ASGITransport, AsyncClient as HttpxClient
        from main import app
        transport = ASGITransport(app=app)
        async with HttpxClient(transport=transport, base_url="http://test") as http:
            resp = await http.post("/api/v1/system/check-leases")
        assert resp.status_code == 200
        body = resp.json()
        assert "checked" in body
        assert "released" in body
        assert "forced" in body
        assert "skipped" in body

    async def test_check_leases_processes_expired_lease(self, client_and_queue):
        """Expired active lease is released when storefront patch succeeds."""
        from unittest.mock import AsyncMock, patch as mock_patch
        from httpx import ASGITransport, AsyncClient as HttpxClient
        from main import app
        import container as _container_module

        client, _ = client_and_queue

        # Create a lease that is already expired
        expired_lease = await client.register_lease(
            resource_id="compute-ww1-001",
            escrow_uid="esc-check-test",
            vm_host="ww1",
            vm_target="tenant-test",
            lease_end_utc=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
        )
        assert expired_lease["status"] == "active"

        lease_check_svc = _container_module.resolved_lease_check_service
        transport = ASGITransport(app=app)
        async with HttpxClient(transport=transport, base_url="http://test") as http:
            with mock_patch.object(
                lease_check_svc,
                "_patch_storefront_resource",
                new=AsyncMock(return_value=True),
            ):
                resp = await http.post("/api/v1/system/check-leases")

        assert resp.status_code == 200
        body = resp.json()
        assert body["released"] >= 1

        fetched = await client.get_lease(expired_lease["id"])
        assert fetched["status"] == "released"
