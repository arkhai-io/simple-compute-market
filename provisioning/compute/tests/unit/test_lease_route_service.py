"""The lease routes' refusals, filters, and view, over fake collaborators."""

from __future__ import annotations


import pytest
from compute_provisioning_contracts import (
    LeaseReleaseOversight,
    LeaseState,
    LeaseTermination,
)

from compute_provisioning.lease_lifecycle import InvalidLeaseStateError, LeaseNotFoundError
from compute_provisioning.leases import LeaseRouteService
from compute_provisioning.route_errors import ProvisioningRouteError


def _reservation(reservation_id: str, mode: str, state: str = "leased") -> dict:
    return {
        "capacity_reservation_id": reservation_id,
        "offering_mode": mode,
        "state": state,
        "executor_target": f"target-{reservation_id}",
        "deal_ref": {"escrow_uid": "0x1"},
        "lease_start_utc": "2026-01-01T00:00:00+00:00",
        "lease_end_utc": "2099-01-01 00:00",
    }


class FakeLeases:
    def __init__(self, *reservations: dict) -> None:
        self.reservations = {r["capacity_reservation_id"]: r for r in reservations}

    def list_leases(self):
        return list(self.reservations.values())

    def get_lease(self, lease_id):
        if lease_id not in self.reservations:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found")
        return self.reservations[lease_id]


class FakeLifecycle:
    def __init__(self, refuse: Exception | None = None) -> None:
        self.refuse = refuse

    async def terminate_lease(self, lease_id, body):
        if self.refuse is not None:
            raise self.refuse
        return {**_reservation(lease_id, "vm", "releasing"), "release_job_id": "f-1"}

    def release_oversight(self, lease_id, body):
        if self.refuse is not None:
            raise self.refuse
        return _reservation(lease_id, "vm", "unmanaged")


def test_the_list_filters_by_status_and_offering_mode():
    service = LeaseRouteService(
        FakeLeases(
            _reservation("vm-1", "vm"),
            _reservation("bm-1", "bare_metal"),
            _reservation("bm-2", "bare_metal", "releasing"),
        ),
        FakeLifecycle(),
    )

    everything = service.list()
    bare_metal = service.list(offering_mode="bare_metal")
    releasing = service.list(status=LeaseState.RELEASING)

    assert everything.total == 3
    assert {lease.capacity_reservation_id for lease in bare_metal.leases} == {"bm-1", "bm-2"}
    assert [lease.capacity_reservation_id for lease in releasing.leases] == ["bm-2"]


def test_a_missing_lease_is_not_found():
    with pytest.raises(ProvisioningRouteError) as refused:
        LeaseRouteService(FakeLeases(), FakeLifecycle()).get("missing")

    assert refused.value.status_code == 404


@pytest.mark.asyncio
async def test_a_terminate_the_lease_s_state_refuses_is_a_conflict():
    service = LeaseRouteService(
        FakeLeases(),
        FakeLifecycle(refuse=InvalidLeaseStateError("admin repair is required", state="release_failed")),
    )

    with pytest.raises(ProvisioningRouteError) as refused:
        await service.terminate("vm-1", LeaseTermination())

    assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_terminate_and_oversight_report_the_lease_view():
    service = LeaseRouteService(FakeLeases(), FakeLifecycle())

    terminated = await service.terminate("vm-1", LeaseTermination())
    handed = service.release_oversight("vm-1", LeaseReleaseOversight(reason="operator check"))

    assert (terminated.status, terminated.release_job_id) == (LeaseState.RELEASING, "f-1")
    assert handed.status == LeaseState.UNMANAGED


def test_a_reservation_recording_no_mode_is_a_conflict_not_a_guess():
    corrupt = {**_reservation("vm-1", "vm"), "offering_mode": None}

    with pytest.raises(ProvisioningRouteError) as refused:
        LeaseRouteService(FakeLeases(corrupt), FakeLifecycle()).get("vm-1")

    assert refused.value.status_code == 409
