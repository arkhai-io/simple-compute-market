"""The executor refuses to dispatch a privileged play for a non-lease account."""

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


def _service(job_service: RecordingJobService) -> BareMetalOperationsService:
    return BareMetalOperationsService(
        job_service=job_service,
        job_queue_provider=lambda: object(),
        settings=SimpleNamespace(bare_metal_reclaim_policy="remove_lease_key"),
        host_service=AllowingHosts(),
    )


def _lease(access_ref: dict, **identity) -> BareMetalLeaseCreate:
    if not identity:
        identity = {"escrow_uid": ESCROW}
    return BareMetalLeaseCreate(
        capacity_reservation_id="res-1",
        machine_id=MACHINE,
        physical_host_id="host-1",
        lease_start_utc=datetime(2030, 1, 1, tzinfo=timezone.utc),
        lease_end_utc=datetime(2030, 1, 2, tzinfo=timezone.utc),
        access_ref=access_ref,
        **identity,
    )


def _grant_ref(ssh_user: str) -> dict:
    return {"ssh_user": ssh_user, "ssh_public_key": "ssh-ed25519 AAAA test"}


def _reservation(ssh_user: str, **identity) -> dict:
    reservation = {
        "capacity_reservation_id": "res-1",
        "executor_target": MACHINE,
        "executor_ref": {
            "physical_host_id": "host-1",
            "ssh_user": ssh_user,
            "ssh_public_key": "ssh-ed25519 AAAA test",
        },
    }
    reservation.update(identity)
    return reservation


@pytest.mark.asyncio
async def test_grant_dispatches_the_derived_lease_account() -> None:
    jobs = RecordingJobService()

    await _service(jobs).grant_access(_lease(_grant_ref(canonical_lease_account(ESCROW))))

    assert [params.ssh_user for params in jobs.submitted] == [canonical_lease_account(ESCROW)]


@pytest.mark.asyncio
async def test_grant_derives_from_an_obligation_identity() -> None:
    jobs = RecordingJobService()
    account = canonical_lease_account("obligation-1")

    await _service(jobs).grant_access(
        _lease(_grant_ref(account), settlement_obligation_ref="obligation-1")
    )

    assert jobs.submitted[0].ssh_user == account


@pytest.mark.parametrize("candidate", ["root", "opsadmin", "ubuntu", "admin", "arkhai"])
@pytest.mark.asyncio
async def test_grant_refuses_an_operator_account(candidate: str) -> None:
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).grant_access(_lease(_grant_ref(candidate)))

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_grant_refuses_another_settlements_account() -> None:
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).grant_access(
            _lease(_grant_ref(canonical_lease_account("escrow-xyz")))
        )

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_grant_refuses_a_lease_with_no_account() -> None:
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).grant_access(
            _lease({"ssh_public_key": "ssh-ed25519 AAAA test"})
        )

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_grant_ignores_the_legacy_user_alias_for_admission() -> None:
    """An alternative key cannot smuggle an unadmitted name past the check."""
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).grant_access(
            _lease({"user": "root", "ssh_public_key": "ssh-ed25519 AAAA test"})
        )

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_reclaim_dispatches_the_derived_lease_account() -> None:
    jobs = RecordingJobService()

    await _service(jobs).reclaim_access(
        _reservation(canonical_lease_account(ESCROW), escrow_uid=ESCROW)
    )

    assert jobs.submitted[0].ssh_user == canonical_lease_account(ESCROW)


@pytest.mark.parametrize("candidate", ["root", "opsadmin", "ubuntu"])
@pytest.mark.asyncio
async def test_reclaim_refuses_an_operator_account(candidate: str) -> None:
    """Lock and delete reclaim policies act on an existing account."""
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access(_reservation(candidate, escrow_uid=ESCROW))

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_reclaim_binds_the_account_to_the_stored_settlement() -> None:
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access(
            _reservation(canonical_lease_account("escrow-xyz"), escrow_uid=ESCROW)
        )
    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access(
            _reservation(
                canonical_lease_account(ESCROW),
                settlement_obligation_ref="obligation-1",
            )
        )

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_reclaim_without_a_settlement_identity_is_refused() -> None:
    """Without the lease's identity no account can be bound to that lease."""
    jobs = RecordingJobService()

    for candidate in (canonical_lease_account("other"), "root"):
        with pytest.raises(BareMetalLeaseAccountError):
            await _service(jobs).reclaim_access(_reservation(candidate))

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_reclaim_resolves_a_hosted_obligation_from_the_site_deal_ref() -> None:
    """A site reservation carries a hosted lease's identity in its deal reference."""
    jobs = RecordingJobService()
    deal_ref = {"negotiation_id": "negotiation-1", "hosted_obligation_ref": "obligation-1"}

    await _service(jobs).reclaim_access(
        _reservation(
            canonical_lease_account("obligation-1"),
            escrow_uid=None,
            deal_ref=deal_ref,
        )
    )
    assert [params.ssh_user for params in jobs.submitted] == [
        canonical_lease_account("obligation-1")
    ]

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access(
            _reservation(canonical_lease_account(ESCROW), escrow_uid=None, deal_ref=deal_ref)
        )
    assert len(jobs.submitted) == 1


@pytest.mark.asyncio
async def test_reclaim_refuses_conflicting_settlement_identities() -> None:
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access(
            _reservation(
                canonical_lease_account(ESCROW),
                escrow_uid=ESCROW,
                settlement_obligation_ref="obligation-1",
            )
        )

    assert jobs.submitted == []


@pytest.mark.asyncio
async def test_release_delegate_surfaces_an_admission_refusal() -> None:
    """A refused reclaim must not read as a released reservation."""
    jobs = RecordingJobService()

    with pytest.raises(BareMetalLeaseAccountError):
        await _service(jobs).reclaim_access_for_reservation(
            _reservation("root", escrow_uid=ESCROW)
        )

    assert jobs.submitted == []
