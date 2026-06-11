"""Integration tests for the VM leases API — a view over the ledger.

The lease is the temporal tail of a capacity-ledger allocation; the
``/api/v1/leases`` surface attaches lease tails to live allocations and
reads them back in lease vocabulary.

Coverage:
  - POST /api/v1/leases: attaches to the reservation's allocation;
    404 when no live allocation matches
  - GET /api/v1/leases: list (only allocations carrying a lease tail)
  - GET /api/v1/leases/{id} and /by-escrow/{uid}
  - POST /api/v1/system/check-leases: one watchdog cycle over the ledger

What is NOT covered here (unit test jurisdiction):
  - CapacityLedgerService transition logic
  - LeaseLifecycleService grace period and force logic
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import container as _container_module
import pytest

from client.provisioning_client import ProvisioningError


def _future_dt(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _past_dt(seconds: int = 10) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _reserve(escrow_uid: str, *, gpu_count: int = 1) -> dict:
    """Reserve capacity in the ledger the way a storefront deal does."""
    ledger = _container_module.resolved_capacity_ledger_service
    if "compute-kvm1-001" not in {
        r["resource_id"] for r in ledger.list_resources()
    }:
        ledger.register_resource(
            resource_id="compute-kvm1-001",
            total_units=8,
            attributes={"vm_host": "kvm1"},
        )
    reserved = ledger.reserve(
        claim={"gpu_count": gpu_count}, deal_ref={"escrow_uid": escrow_uid},
    )
    assert reserved is not None
    return reserved


async def _register(client, escrow_uid: str, **overrides) -> dict:
    reserved = _reserve(escrow_uid)
    body = {
        "resource_id": reserved["resource_id"],
        "allocation_id": reserved["allocation_id"],
        "escrow_uid": escrow_uid,
        "vm_host": "kvm1",
        "vm_target": f"tenant-{escrow_uid[-4:]}",
        "lease_end_utc": _future_dt(),
    }
    body.update(overrides)
    return await client.register_lease(**body)


class TestCreateLease:
    async def test_create_attaches_to_the_allocation(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _register(client, "escrow-attach-1")
        assert lease["status"] == "active"
        assert lease["escrow_uid"] == "escrow-attach-1"
        assert lease["vm_host"] == "kvm1"

        ledger = _container_module.resolved_capacity_ledger_service
        allocation = ledger.get_allocation(lease["allocation_id"])
        assert allocation["state"] == "leased"
        assert allocation["vm_target"] == lease["vm_target"]

    async def test_create_unknown_allocation_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.register_lease(
                resource_id="compute-kvm1-001",
                allocation_id="not-a-ledger-allocation",
                escrow_uid="escrow-ghost",
                vm_host="kvm1",
                vm_target="tenant-ghost",
                lease_end_utc=_future_dt(),
            )
        assert exc_info.value.status_code == 404


class TestListLeases:
    async def test_empty_returns_empty_list(self, client_and_queue):
        client, _ = client_and_queue
        result = await client.list_leases()
        assert result["total"] == 0
        assert result["leases"] == []

    async def test_lists_attached_leases_only(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client, "escrow-list-1")
        _reserve("escrow-no-lease")  # a bare hold has no lease tail
        result = await client.list_leases()
        assert result["total"] == 1
        assert result["leases"][0]["escrow_uid"] == "escrow-list-1"

    async def test_filter_by_escrow_uid(self, client_and_queue):
        client, _ = client_and_queue
        await _register(client, "escrow-filter-1")
        await _register(client, "escrow-filter-2")
        result = await client.list_leases(escrow_uid="escrow-filter-2")
        assert result["total"] == 1
        assert result["leases"][0]["escrow_uid"] == "escrow-filter-2"


class TestGetLease:
    async def test_get_by_id(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _register(client, "escrow-get-1")
        fetched = await client.get_lease(lease["id"])
        assert fetched["escrow_uid"] == "escrow-get-1"
        assert fetched["status"] == "active"

    async def test_get_nonexistent_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_lease("missing-lease")
        assert exc_info.value.status_code == 404

    async def test_get_by_escrow(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _register(client, "escrow-by-escrow-1")
        fetched = await client.get_lease_by_escrow("escrow-by-escrow-1")
        assert fetched["id"] == lease["id"]

    async def test_get_by_escrow_nonexistent_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.get_lease_by_escrow("escrow-missing")
        assert exc_info.value.status_code == 404


class TestCheckLeasesEndpoint:
    async def test_check_leases_releases_expired_ledger_lease(self, client_and_queue):
        """The on-demand cycle releases an expired lease in the ledger and
        emits the capacity event (deal notification is best-effort and the
        test storefront is unreachable — that must not block the release)."""
        client, _ = client_and_queue
        lease = await _register(
            client, "escrow-expired-1", lease_end_utc=_past_dt(),
        )

        result = await client.check_leases()
        assert result.get("released", 0) >= 1

        ledger = _container_module.resolved_capacity_ledger_service
        allocation = ledger.get_allocation(lease["allocation_id"])
        assert allocation["state"] == "released"
        events, _ = ledger.events_after(0)
        assert events[-1]["kind"] == "released"
