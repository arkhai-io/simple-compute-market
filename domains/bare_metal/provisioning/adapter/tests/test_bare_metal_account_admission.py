"""The executor refuses to run a privileged play against a non-lease account."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from arkhai_bare_metal import (
    BareMetalLeaseAccountError,
    BareMetalLeaseCreate,
    canonical_lease_account,
)

from bare_metal_provisioning_adapter.services.bare_metal_operations_service import (
    BareMetalOperationsService,
)

ESCROW = "escrow-abc"
MACHINE = "node-1"


class RecordingJobService:
    def __init__(self) -> None:
        self.submitted: list = []

    async def submit(self, params, queue, *, contract=None, operation_id=None):
        self.submitted.append(params)
        return SimpleNamespace(job_id="job-1")


class AllowingHosts:
    def get_host(self, machine_id):
        return SimpleNamespace(enabled=True, name=machine_id)


def _service(job_service=None) -> BareMetalOperationsService:
    return BareMetalOperationsService(
        job_service=job_service or RecordingJobService(),
        job_queue_provider=lambda: object(),
        settings=SimpleNamespace(bare_metal_reclaim_policy="remove_lease_key"),
        host_service=AllowingHosts(),
    )


def _lease(ssh_user: str) -> BareMetalLeaseCreate:
    return BareMetalLeaseCreate(
        capacity_reservation_id="res-1",
        escrow_uid=ESCROW,
        machine_id=MACHINE,
        physical_host_id="host-1",
        lease_start_utc=datetime(2030, 1, 1, tzinfo=timezone.utc),
        lease_end_utc=datetime(2030, 1, 2, tzinfo=timezone.utc),
        access_ref={
            "ssh_user": ssh_user,
            "ssh_public_key": "ssh-ed25519 AAAA test",
        },
    )


@pytest.mark.asyncio
async def test_grant_accepts_the_derived_lease_account() -> None:
    jobs = RecordingJobService()

    await _service(jobs).grant_access(_lease(canonical_lease_account(ESCROW)))

    assert len(jobs.submitted) == 1
    assert jobs.submitted[0].ssh_user == canonical_lease_account(ESCROW)


@pytest.mark.parametrize("privileged", ["root", "opsadmin", "ubuntu", "admin", "arkhai"])
@pytest.mark.asyncio
async def test_grant_refuses_an_operator_account(privileged: str) -> None:
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).grant_access(_lease(privileged))

    assert jobs.submitted == [], "no privileged play may be dispatched"


@pytest.mark.asyncio
async def test_grant_refuses_an_account_from_another_settlement() -> None:
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).grant_access(_lease(canonical_lease_account("escrow-xyz")))

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_grant_refuses_a_lease_with_no_account() -> None:
    jobs = RecordingJobService()
    lease = BareMetalLeaseCreate(
        capacity_reservation_id="res-1",
        escrow_uid=ESCROW,
        machine_id=MACHINE,
        physical_host_id="host-1",
        lease_end_utc=datetime(2030, 1, 2, tzinfo=timezone.utc),
        access_ref={"ssh_public_key": "ssh-ed25519 AAAA test"},
    )

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).grant_access(lease)

    assert jobs.submitted == []


def _reservation(ssh_user: str, *, escrow: str | None = ESCROW) -> dict:
    return {
        "capacity_reservation_id": "res-1",
        "executor_target": MACHINE,
        "escrow_uid": escrow,
        "executor_ref": {
            "physical_host_id": "host-1",
            "ssh_user": ssh_user,
            "ssh_public_key": "ssh-ed25519 AAAA test",
        },
    }


@pytest.mark.asyncio
async def test_reclaim_accepts_the_derived_lease_account() -> None:
    jobs = RecordingJobService()

    await _service(jobs).reclaim_access(_reservation(canonical_lease_account(ESCROW)))

    assert len(jobs.submitted) == 1


@pytest.mark.parametrize("privileged", ["root", "opsadmin", "ubuntu"])
@pytest.mark.asyncio
async def test_reclaim_refuses_an_operator_account(privileged: str) -> None:
    """`lock_user` and `delete_user` are destructive; refuse before dispatch."""
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access(_reservation(privileged))

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_reclaim_without_a_recoverable_identity_still_requires_lease_shape() -> None:
    jobs = RecordingJobService()

    await _service(jobs).reclaim_access(
        _reservation(canonical_lease_account("some-other-identity"), escrow=None)
    )
    assert len(jobs.submitted) == 1

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access(_reservation("root", escrow=None))
    assert len(jobs.submitted) == 1


@pytest.mark.asyncio
async def test_release_delegate_does_not_swallow_an_admission_refusal() -> None:
    """A refused reclaim must surface, not report the reservation as released.

    Returning ``None`` here would let the capacity ledger treat a host that
    still carries a buyer key as released.
    """
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access_for_reservation(_reservation("root"))

    assert jobs.submitted == []
