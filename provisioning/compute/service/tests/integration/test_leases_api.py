"""Integration tests for the VM leases API — a view over the ledger.

The lease is the temporal tail of a capacity-ledger reservation; the
``/api/v1/leases`` surface attaches lease tails to live reservations and
reads them back in lease vocabulary.

Coverage:
  - POST /api/v1/leases: attaches to the reservation's reservation;
    404 when no live reservation matches
  - GET /api/v1/leases: list (only reservations carrying a lease tail)
  - GET /api/v1/leases/{id} and /by-escrow/{uid}
  - POST /api/v1/system/check-leases: one watchdog cycle over the ledger

What is NOT covered here (unit test jurisdiction):
  - CapacityLedgerService transition logic
  - LeaseLifecycleService grace period and force logic
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from compute_provisioning_service import container as _container_module
import pytest

from vm_provisioning_operator import ProvisioningError


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
        claim={"gpu_count": gpu_count, "vm_host": "kvm1"},
        deal_ref={"escrow_uid": escrow_uid},
    )
    assert reserved is not None
    return reserved


async def _register(client, escrow_uid: str, **overrides) -> dict:
    reserved = _reserve(escrow_uid)
    body = {
        "resource_id": "compute-kvm1-001",
        "capacity_reservation_id": reserved["capacity_reservation_id"],
        "escrow_uid": escrow_uid,
        "vm_host": "kvm1",
        "vm_target": f"tenant-{escrow_uid[-4:]}",
        "lease_end_utc": _future_dt(),
    }
    body.update(overrides)
    return await client.register_lease(**body)


class TestCreateLease:
    async def test_create_attaches_to_the_reservation(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _register(client, "escrow-attach-1")
        assert lease["status"] == "active"
        assert lease["escrow_uid"] == "escrow-attach-1"
        assert lease["vm_host"] == "kvm1"

        ledger = _container_module.resolved_capacity_ledger_service
        reservation = ledger.get_reservation(lease["capacity_reservation_id"])
        assert reservation["state"] == "leased"
        assert reservation["vm_target"] == lease["vm_target"]
        assert reservation["executor_kind"] == "vm"
        assert reservation["executor_target"] == lease["vm_target"]
        assert reservation["executor_ref"] == {"vm_host": "kvm1"}

    async def test_create_unknown_reservation_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.register_lease(
                resource_id="compute-kvm1-001",
                capacity_reservation_id="not-a-ledger-reservation",
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
    async def test_legacy_vm_lease_without_fulfillment_stays_held(self, client_and_queue):
        """VM release has no direct fallback after fulfillment cutover."""
        client, _ = client_and_queue
        lease = await _register(
            client, "escrow-expired-1", lease_end_utc=_past_dt(),
        )

        result = await client.check_leases()
        assert result.get("release_failed", 0) == 1

        ledger = _container_module.resolved_capacity_ledger_service
        reservation = ledger.get_reservation(lease["capacity_reservation_id"])
        assert reservation["state"] == "release_failed"
        events, _ = ledger.events_after(0)
        assert events[-1]["kind"] != "released"


class TestUpdateLease:
    async def test_patch_lease_end_utc(self, client_and_queue):
        """PATCH updates lease_end_utc without changing the reservation state."""
        client, _ = client_and_queue
        lease = await _register(client, "escrow-patch-1")
        new_end = _future_dt(hours=4)

        updated = await client.update_lease(lease["id"], lease_end_utc=new_end)

        assert updated["id"] == lease["id"]
        assert updated["status"] == "active"  # state unchanged
        ledger = _container_module.resolved_capacity_ledger_service
        reservation = ledger.get_reservation(lease["capacity_reservation_id"])
        assert reservation["state"] == "leased"
        # The new end time was stored (compare prefix to avoid TZ formatting differences)
        assert reservation["lease_end_utc"].startswith(new_end[:19])

    async def test_patch_vm_host_and_vm_target(self, client_and_queue):
        """PATCH can update vm_host and vm_target for migrated VMs."""
        client, _ = client_and_queue
        lease = await _register(client, "escrow-patch-2")

        updated = await client.update_lease(
            lease["id"], vm_host="kvm2", vm_target="migrated-vm",
        )

        assert updated["vm_host"] == "kvm2"
        assert updated["vm_target"] == "migrated-vm"
        assert updated["status"] == "active"

    async def test_patch_through_generic_executor_lease_service(
        self, client_and_queue, monkeypatch,
    ):
        """The VM controller can update through the executor-neutral service."""
        from compute_provisioning.executor_leases import ExecutorLeaseService
        from market_site.authority import LedgerSiteAuthority

        client, _ = client_and_queue
        lease = await _register(client, "escrow-patch-generic")
        generic_leases = ExecutorLeaseService(
            LedgerSiteAuthority(_container_module.resolved_capacity_ledger_service),
            executor_kind="vm",
        )
        monkeypatch.setattr(
            _container_module,
            "resolved_lease_lifecycle_service",
            generic_leases,
        )

        updated = await client.update_lease(
            lease["id"],
            vm_host="kvm-generic",
            vm_target="generic-migrated-vm",
        )

        assert updated["vm_host"] == "kvm-generic"
        assert updated["vm_target"] == "generic-migrated-vm"


    async def test_patch_nonexistent_lease_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.update_lease("no-such-lease", lease_end_utc=_future_dt())
        assert exc_info.value.status_code == 404

    async def test_patch_backdated_legacy_vm_lease_fails_closed(self, client_and_queue):
        """A lease without a fulfillment aggregate has no VM release fallback."""
        client, _ = client_and_queue
        lease = await _register(client, "escrow-patch-backdate")

        await client.update_lease(lease["id"], lease_end_utc=_past_dt())
        result = await client.check_leases()

        assert result.get("release_failed", 0) == 1
        ledger = _container_module.resolved_capacity_ledger_service
        reservation = ledger.get_reservation(lease["capacity_reservation_id"])
        assert reservation["state"] == "release_failed"


class TestReleaseOversight:
    async def test_release_oversight_marks_unmanaged_without_releasing_capacity(self, client_and_queue):
        """release-oversight marks unmanaged and leaves capacity held."""
        client, _ = client_and_queue
        lease = await _register(client, "escrow-unmanaged-1")

        unmanaged = await client.release_lease_oversight(
            lease["id"], reason="operator will manage manually",
        )

        assert unmanaged["status"] == "unmanaged"
        ledger = _container_module.resolved_capacity_ledger_service
        reservation = ledger.get_reservation(lease["capacity_reservation_id"])
        assert reservation["state"] == "unmanaged"
        snapshot = ledger.snapshot()
        resource = next(r for r in snapshot if r["resource_id"] == "compute-kvm1-001")
        assert resource["available_units"] < resource["value"]

    async def test_release_oversight_does_not_emit_capacity_event(self, client_and_queue):
        client, _ = client_and_queue
        ledger = _container_module.resolved_capacity_ledger_service

        lease = await _register(client, "escrow-unmanaged-event")
        _, version_before = ledger.events_after(0)

        await client.release_lease_oversight(lease["id"], reason="manual ops")

        events, _ = ledger.events_after(version_before)
        kinds = [e["kind"] for e in events]
        assert "released" not in kinds

    async def test_release_oversight_nonexistent_returns_404(self, client_and_queue):
        client, _ = client_and_queue
        with pytest.raises(ProvisioningError) as exc_info:
            await client.release_lease_oversight("no-such-lease", reason="manual ops")
        assert exc_info.value.status_code == 404

    async def test_release_oversight_releasing_returns_409(self, client_and_queue):
        """release-oversight on a releasing reservation returns 409."""
        client, _ = client_and_queue
        lease = await _register(client, "escrow-cancel-releasing", lease_end_utc=_past_dt())
        ledger = _container_module.resolved_capacity_ledger_service
        # Manually transition to releasing (simulating watchdog having fired)
        ledger.begin_releasing(lease["capacity_reservation_id"], vm_remove_job_id="job-in-flight")

        with pytest.raises(ProvisioningError) as exc_info:
            await client.release_lease_oversight(lease["id"], reason="manual ops")
        assert exc_info.value.status_code == 409



class TestAdminLeaseRepair:
    async def test_legacy_vm_retry_has_no_direct_release_fallback(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _register(client, "escrow-retry-release", lease_end_utc=_past_dt())
        ledger = _container_module.resolved_capacity_ledger_service
        ledger.update_reservation_state(
            lease["capacity_reservation_id"],
            state="release_failed",
            failure_reason="vm_remove_failed",
            failure_message="cleanup script missing",
        )

        with pytest.raises(ProvisioningError) as exc_info:
            await client.retry_lease_release(lease["id"], reason="operator retry")
        assert exc_info.value.status_code == 409
        reservation = ledger.get_reservation(lease["capacity_reservation_id"])
        assert reservation["state"] == "release_failed"

    async def test_retry_release_non_failed_returns_409(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _register(client, "escrow-retry-active")

        with pytest.raises(ProvisioningError) as exc_info:
            await client.retry_lease_release(lease["id"], reason="operator retry")
        assert exc_info.value.status_code == 409

    async def test_force_release_unmanaged_releases_capacity(self, client_and_queue):
        client, _ = client_and_queue
        lease = await _register(client, "escrow-force-unmanaged")
        ledger = _container_module.resolved_capacity_ledger_service
        await client.release_lease_oversight(lease["id"], reason="manual ops")
        _, version_before = ledger.events_after(0)

        released = await client.force_release_lease(
            lease["id"], reason="host inspected", evidence="VM absent",
        )

        assert released["status"] == "force_released"
        reservation = ledger.get_reservation(lease["capacity_reservation_id"])
        assert reservation["state"] == "force_released"
        assert reservation["failure_reason"] == "admin_force_release"
        events, _ = ledger.events_after(version_before)
        assert [event["kind"] for event in events] == ["released"]
        snapshot = ledger.snapshot()
        resource = next(r for r in snapshot if r["resource_id"] == "compute-kvm1-001")
        assert resource["available_units"] == resource["value"]

    async def test_force_release_invalid_state_returns_409(self, client_and_queue):
        client, _ = client_and_queue
        reserved = _reserve("escrow-force-reserved")

        with pytest.raises(ProvisioningError) as exc_info:
            await client.force_release_lease(
                reserved["capacity_reservation_id"], reason="not a lease yet",
            )
        assert exc_info.value.status_code == 409
