"""Watchdog over ledger allocations: local release + deal event, no PATCH.

The legacy vm_leases leg keeps its own tests
(test_lease_lifecycle_service.py); these cover the merged-row leg added
for remote-capacity mode — release happens in the ledger's local
transaction, the owning storefront gets a point-to-point
capacity-released event, and the resource PATCH callback never fires.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base
from compute_provisioning.release import ExecutorReleaseDispatcher
from market_site.authority import LedgerSiteAuthority
from market_site.ledger import CapacityLedgerService
from compute_provisioning.lease_lifecycle import LeaseLifecycleService
from services.deal_event_sink import notify_storefront_capacity_released
from services.release_executors import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalReleaseExecutor,
    VM_EXECUTOR_KIND,
    VmReleaseExecutor,
    bare_metal_executor_ref,
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # resource_pools must exist before Base's ansible_pool_configs FK resolves.
    from market_resource_pools.db import Base as PoolsBase
    PoolsBase.metadata.create_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # Site-ledger tables ride market_site's own metadata.
    from market_site.db import Base as SiteBase
    SiteBase.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def ledger(session_factory) -> CapacityLedgerService:
    svc = CapacityLedgerService(session_factory)
    svc.register_resource(
        resource_id="compute-kvm1-001",
        total_units=8,
        attributes={"vm_host": "kvm1"},
    )
    return svc


def _settings(**overrides):
    s = MagicMock()
    s.lease_watchdog_grace_period_seconds = 300
    s.storefront_url = "http://storefront:8001"
    s.storefront_admin_key = "admin-key"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


class DelegateReleaseExecutor:
    def __init__(self, delegate):
        self._delegate = delegate

    async def submit_release(self, allocation):
        result = self._delegate(allocation)
        if inspect.isawaitable(result):
            return await result
        return result


def _lifecycle(
    session_factory,
    ledger,
    *,
    job_service=None,
    executor_release=None,
    release_delegate=None,
    **settings_overrides,
):
    if executor_release is None:
        executors = {
            BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(),
            VM_EXECUTOR_KIND: VmReleaseExecutor(
                job_service=job_service,
                job_queue_provider=lambda: MagicMock(),
            ),
        }
        if release_delegate is not None:
            executors[VM_EXECUTOR_KIND] = DelegateReleaseExecutor(release_delegate)
        executor_release = ExecutorReleaseDispatcher(
            executors,
            default_executor_kind=VM_EXECUTOR_KIND,
        )
    settings = _settings(**settings_overrides)
    return LeaseLifecycleService(
        settings=settings,
        site_authority=LedgerSiteAuthority(ledger),
        executor_release=executor_release,
        release_jobs=job_service,
        capacity_released_notifier=(
            lambda allocation: notify_storefront_capacity_released(settings, allocation)
        ),
    )


def _expired_allocation(ledger: CapacityLedgerService, escrow: str = "0xe") -> dict:
    reserved = ledger.reserve(
        claim={"gpu_count": 2, "vm_host": "kvm1"},
        deal_ref={"escrow_uid": escrow},
    )
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_start_utc="2020-01-01T00:00:00Z",
        lease_end_utc="2020-01-01 00:00",
    )
    ledger.attach_lease(
        allocation_id=reserved["allocation_id"],
        vm_host="kvm1", vm_target="tenant-x",
        lease_end_utc="2020-01-01 00:00",
    )
    return reserved


def _just_expired_allocation(ledger: CapacityLedgerService, escrow: str = "0xe") -> dict:
    reserved = ledger.reserve(
        claim={"gpu_count": 2, "vm_host": "kvm1"},
        deal_ref={"escrow_uid": escrow},
    )
    just_expired_dt = datetime.now(timezone.utc) - timedelta(seconds=1)
    just_expired = just_expired_dt.isoformat()
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_start_utc=(just_expired_dt - timedelta(seconds=3600)).isoformat(),
        lease_end_utc=just_expired,
    )
    ledger.attach_lease(
        allocation_id=reserved["allocation_id"],
        vm_host="kvm1",
        vm_target="tenant-x",
        lease_end_utc=just_expired,
    )
    return reserved


@pytest.mark.asyncio
async def test_expired_ledger_lease_releases_locally_and_notifies(
    session_factory, ledger,
):
    allocation = _expired_allocation(ledger)
    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})
    sf.patch_resource = AsyncMock()

    with patch(
        "storefront_client.StorefrontClient", return_value=sf,
    ) as client_cls:
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    released = ledger.get_allocation(allocation["allocation_id"])
    assert released["state"] == "released"
    assert ledger.snapshot()[0]["available_units"] == 8

    # Deal event went to the owning storefront; the legacy PATCH did not.
    client_cls.assert_called_once_with(
        base_url="http://storefront:8001", admin_key="admin-key",
    )
    sf.notify_capacity_released.assert_awaited_once()
    args, kwargs = sf.notify_capacity_released.await_args
    assert args == (allocation["allocation_id"],)
    assert kwargs["resource_id"] == "compute-kvm1-001"
    sf.patch_resource.assert_not_awaited()

    # The anonymous capacity feed carries the release for subscribers.
    events, _ = ledger.events_after(0)
    assert events[-1]["kind"] == "released"


@pytest.mark.asyncio
async def test_release_survives_unreachable_storefront(session_factory, ledger):
    """The local transaction is authoritative; notification is best-effort
    (the storefront converges through the capacity-event feed)."""
    allocation = _expired_allocation(ledger)
    svc = _lifecycle(session_factory, ledger)

    with patch(
        "storefront_client.StorefrontClient",
        side_effect=ConnectionError("storefront down"),
    ):
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_allocation(allocation["allocation_id"])["state"] == "released"


@pytest.mark.asyncio
async def test_releasing_allocation_past_grace_marks_release_failed(
    session_factory, ledger,
):
    allocation = _expired_allocation(ledger)
    ledger.begin_releasing(allocation["allocation_id"], vm_remove_job_id="check-1")

    job_svc = MagicMock()
    running = MagicMock()
    running.status = "running"
    job_svc.get_job.return_value = running

    svc = _lifecycle(session_factory, ledger, job_service=job_svc)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        # lease ended 2020 + 300s grace — long past: still-running vm_remove
        # job is marked failed; capacity remains held.
        summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    assert ledger.get_allocation(allocation["allocation_id"])["state"] == "release_failed"
    assert ledger.snapshot()[0]["available_units"] < 8
    sf.notify_capacity_released.assert_not_awaited()


@pytest.mark.asyncio
async def test_releasing_allocation_within_grace_skips(session_factory, ledger):
    reserved = ledger.reserve(claim={}, deal_ref={})
    soon_dt = datetime.now(timezone.utc) - timedelta(seconds=1)
    soon = soon_dt.isoformat()
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_start_utc=(soon_dt - timedelta(seconds=3600)).isoformat(),
        lease_end_utc=soon,
    )
    ledger.begin_releasing(reserved["allocation_id"], vm_remove_job_id="check-1")

    job_svc = MagicMock()
    running = MagicMock()
    running.status = "running"
    job_svc.get_job.return_value = running

    svc = _lifecycle(session_factory, ledger, job_service=job_svc)
    summary = await svc.force_check_leases()
    assert summary["skipped"] == 1
    assert ledger.get_allocation(reserved["allocation_id"])["state"] == "releasing"


@pytest.mark.asyncio
async def test_succeeded_vm_remove_releases_normally(session_factory, ledger):
    allocation = _expired_allocation(ledger)
    ledger.begin_releasing(allocation["allocation_id"], vm_remove_job_id="check-1")

    job_svc = MagicMock()
    done = MagicMock()
    done.status = "succeeded"
    job_svc.get_job.return_value = done

    svc = _lifecycle(session_factory, ledger, job_service=job_svc)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_allocation(allocation["allocation_id"])["state"] == "released"


@pytest.mark.asyncio
async def test_failed_vm_remove_marks_release_failed_without_notification(session_factory, ledger):
    allocation = _expired_allocation(ledger)
    ledger.begin_releasing(allocation["allocation_id"], vm_remove_job_id="remove-1")

    job_svc = MagicMock()
    failed = MagicMock()
    failed.status = "failed"
    failed.error = "cleanup script missing"
    job_svc.get_job.return_value = failed

    svc = _lifecycle(session_factory, ledger, job_service=job_svc)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    assert ledger.get_allocation(allocation["allocation_id"])["state"] == "release_failed"
    assert ledger.snapshot()[0]["available_units"] < 8
    sf.notify_capacity_released.assert_not_awaited()


@pytest.mark.asyncio
async def test_due_leased_allocation_submits_vm_remove_job(session_factory, ledger):
    # Lease ended seconds ago — within grace, so the same cycle that
    # submits the vm_remove job must NOT force-release it.
    allocation = _just_expired_allocation(ledger)

    job_svc = MagicMock()
    submit = MagicMock()
    submit.job_id = "remove-42"
    job_svc.submit = AsyncMock(return_value=submit)
    running = MagicMock()
    running.status = "running"
    job_svc.get_job.return_value = running

    svc = _lifecycle(session_factory, ledger, job_service=job_svc)

    summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    row = ledger.get_allocation(allocation["allocation_id"])
    assert row["state"] == "releasing"
    assert row["vm_remove_job_id"] == "remove-42"
    assert row["release_job_id"] == "remove-42"
    assert row["executor_kind"] == "vm"
    assert row["executor_target"] == "tenant-x"
    params = job_svc.submit.await_args.args[0]
    assert params.vm_action == "vm_remove"
    assert params.vm_target == "tenant-x"


@pytest.mark.asyncio
async def test_missing_executor_kind_falls_back_to_vm_release(session_factory, ledger):
    allocation = _just_expired_allocation(ledger)

    from market_site.db import SiteAllocation

    with session_factory() as db:
        row = db.get(SiteAllocation, allocation["allocation_id"])
        row.executor_kind = None
        row.executor_target = None
        db.commit()

    job_svc = MagicMock()
    submit = MagicMock()
    submit.job_id = "remove-legacy"
    job_svc.submit = AsyncMock(return_value=submit)

    svc = _lifecycle(session_factory, ledger, job_service=job_svc)

    summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    row = ledger.get_allocation(allocation["allocation_id"])
    assert row["state"] == "releasing"
    assert row["release_job_id"] == "remove-legacy"
    params = job_svc.submit.await_args.args[0]
    assert params.vm_action == "vm_remove"
    assert params.vm_target == "tenant-x"


@pytest.mark.asyncio
async def test_bare_metal_executor_releases_locally_and_notifies(session_factory, ledger):
    allocation = _just_expired_allocation(ledger)
    ledger.update_lease_fields(
        allocation["allocation_id"],
        executor_kind=BARE_METAL_EXECUTOR_KIND,
        executor_target="node-1",
        executor_ref=bare_metal_executor_ref(
            "host-kvm1",
            access_ref={"ssh_user": "tenant-x"},
        ),
    )

    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    assert summary["released"] == 1
    row = ledger.get_allocation(allocation["allocation_id"])
    assert row["state"] == "released"
    assert row["release_job_id"] == "direct-release"
    assert row["vm_remove_job_id"] is None
    assert row["executor_target"] == "node-1"
    assert row["executor_ref"] == {
        "physical_host_id": "host-kvm1",
        "ssh_user": "tenant-x",
    }
    assert ledger.snapshot()[0]["available_units"] == 8
    sf.notify_capacity_released.assert_awaited_once()


@pytest.mark.asyncio
async def test_bare_metal_executor_submits_reclaim_job_when_delegate_configured(
    session_factory, ledger,
):
    allocation = _just_expired_allocation(ledger)
    ledger.update_lease_fields(
        allocation["allocation_id"],
        executor_kind=BARE_METAL_EXECUTOR_KIND,
        executor_target="node-1",
        executor_ref=bare_metal_executor_ref(
            "host-kvm1",
            access_ref={"ssh_user": "tenant-x"},
        ),
    )
    release_delegate = AsyncMock(return_value="reclaim-42")
    dispatcher = ExecutorReleaseDispatcher({
        BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(
            release_delegate=release_delegate,
        ),
    })
    svc = _lifecycle(session_factory, ledger, executor_release=dispatcher)

    summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    row = ledger.get_allocation(allocation["allocation_id"])
    assert row["state"] == "releasing"
    assert row["release_job_id"] == "reclaim-42"
    release_delegate.assert_awaited_once()


@pytest.mark.asyncio
async def test_bare_metal_release_submission_failure_stays_held(session_factory, ledger):
    allocation = _just_expired_allocation(ledger)
    ledger.update_lease_fields(
        allocation["allocation_id"],
        executor_kind=BARE_METAL_EXECUTOR_KIND,
        executor_target="node-1",
    )

    release_delegate = AsyncMock(return_value=None)
    dispatcher = ExecutorReleaseDispatcher({
        BARE_METAL_EXECUTOR_KIND: BareMetalReleaseExecutor(
            release_delegate=release_delegate,
        ),
    })
    svc = _lifecycle(session_factory, ledger, executor_release=dispatcher)

    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_allocation(allocation["allocation_id"])
    assert row["state"] == "release_failed"
    assert row["failure_reason"] == "release_submit_failed"
    assert ledger.snapshot()[0]["available_units"] < 8
    release_delegate.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_executor_kind_stays_held_and_retryable(session_factory, ledger):
    allocation = _just_expired_allocation(ledger)
    ledger.update_lease_fields(
        allocation["allocation_id"],
        executor_kind="custom_executor",
        executor_target="target-1",
    )

    job_svc = MagicMock()
    svc = _lifecycle(session_factory, ledger, job_service=job_svc)

    summary = await svc.force_check_leases()

    assert summary["release_failed"] == 1
    row = ledger.get_allocation(allocation["allocation_id"])
    assert row["state"] == "release_failed"
    assert row["failure_reason"] == "release_submit_failed"
    assert ledger.snapshot()[0]["available_units"] < 8
    job_svc.submit.assert_not_called()


@pytest.mark.asyncio
async def test_admin_retry_release_resubmits_delegate(session_factory, ledger):
    allocation = _expired_allocation(ledger)
    ledger.update_allocation_state(
        allocation["allocation_id"],
        state="release_failed",
        failure_reason="vm_remove_failed",
        failure_message="cleanup script missing",
    )

    delegate = AsyncMock(return_value="remove-retry-1")
    svc = _lifecycle(session_factory, ledger, release_delegate=delegate)

    from vm_provisioning_operator.models import LeaseRetryReleaseRequest

    updated = await svc.retry_release(
        allocation["allocation_id"],
        LeaseRetryReleaseRequest(reason="operator retry"),
    )

    assert updated["state"] == "releasing"
    assert updated["vm_remove_job_id"] == "remove-retry-1"
    assert updated["release_job_id"] == "remove-retry-1"
    assert ledger.snapshot()[0]["available_units"] < 8
    delegate.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_force_release_unmanaged_releases_capacity_and_notifies(session_factory, ledger):
    allocation = _expired_allocation(ledger)
    ledger.update_allocation_state(
        allocation["allocation_id"],
        state="unmanaged",
        failure_reason="oversight_released",
        failure_message="manual ops",
    )

    svc = _lifecycle(session_factory, ledger)

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    from vm_provisioning_operator.models import LeaseForceReleaseRequest

    with patch("storefront_client.StorefrontClient", return_value=sf):
        released = await svc.force_release(
            allocation["allocation_id"],
            LeaseForceReleaseRequest(reason="host inspected", evidence="VM absent"),
        )

    assert released["state"] == "force_released"
    assert released["failure_reason"] == "admin_force_release"
    assert ledger.snapshot()[0]["available_units"] == 8
    events, _ = ledger.events_after(0)
    assert events[-1]["kind"] == "released"
    sf.notify_capacity_released.assert_awaited_once()
