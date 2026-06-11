"""Watchdog over ledger allocations: local release + deal event, no PATCH.

The legacy vm_leases leg keeps its own tests
(test_lease_lifecycle_service.py); these cover the merged-row leg added
for remote-capacity mode — release happens in the ledger's local
transaction, the owning storefront gets a point-to-point
capacity-released event, and the resource PATCH callback never fires.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base
from services.capacity_ledger import CapacityLedgerService
from services.lease_lifecycle_service import LeaseLifecycleService


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
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


def _lifecycle(session_factory, ledger, **settings_overrides):
    return LeaseLifecycleService(
        settings=_settings(**settings_overrides),
        capacity_ledger=ledger,
        job_service=None,  # direct-release path; check jobs covered elsewhere
    )


def _expired_allocation(ledger: CapacityLedgerService, escrow: str = "0xe") -> dict:
    reserved = ledger.reserve(claim={"gpu_count": 2}, deal_ref={"escrow_uid": escrow})
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc="2020-01-01 00:00",
    )
    ledger.attach_lease(
        allocation_id=reserved["allocation_id"],
        vm_host="kvm1", vm_target="tenant-x",
        lease_end_utc="2020-01-01 00:00",
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
async def test_releasing_allocation_waits_for_check_then_grace_forces(
    session_factory, ledger,
):
    allocation = _expired_allocation(ledger)
    ledger.begin_releasing(allocation["allocation_id"], check_job_id="check-1")

    job_svc = MagicMock()
    running = MagicMock()
    running.status = "running"
    job_svc.get_job.return_value = running

    svc = LeaseLifecycleService(
        settings=_settings(),
        capacity_ledger=ledger,
        job_service=job_svc,
    )

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        # lease ended 2020 + 300s grace — long past: still-running check
        # job forces the release.
        summary = await svc.force_check_leases()

    assert summary["forced"] == 1
    assert ledger.get_allocation(allocation["allocation_id"])["state"] == "forced"
    assert ledger.snapshot()[0]["available_units"] == 8
    sf.notify_capacity_released.assert_awaited_once()


@pytest.mark.asyncio
async def test_releasing_allocation_within_grace_skips(session_factory, ledger):
    reserved = ledger.reserve(claim={}, deal_ref={})
    soon = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc=soon,  # expired 1s ago — well within the 300s grace
    )
    ledger.begin_releasing(reserved["allocation_id"], check_job_id="check-1")

    job_svc = MagicMock()
    running = MagicMock()
    running.status = "running"
    job_svc.get_job.return_value = running

    svc = LeaseLifecycleService(
        settings=_settings(),
        capacity_ledger=ledger,
        job_service=job_svc,
    )
    summary = await svc.force_check_leases()
    assert summary["skipped"] == 1
    assert ledger.get_allocation(reserved["allocation_id"])["state"] == "releasing"


@pytest.mark.asyncio
async def test_succeeded_check_releases_normally(session_factory, ledger):
    allocation = _expired_allocation(ledger)
    ledger.begin_releasing(allocation["allocation_id"], check_job_id="check-1")

    job_svc = MagicMock()
    done = MagicMock()
    done.status = "succeeded"
    job_svc.get_job.return_value = done

    svc = LeaseLifecycleService(
        settings=_settings(),
        capacity_ledger=ledger,
        job_service=job_svc,
    )

    sf = MagicMock()
    sf.__aenter__ = AsyncMock(return_value=sf)
    sf.__aexit__ = AsyncMock(return_value=False)
    sf.notify_capacity_released = AsyncMock(return_value={})

    with patch("storefront_client.StorefrontClient", return_value=sf):
        summary = await svc.force_check_leases()

    assert summary["released"] == 1
    assert ledger.get_allocation(allocation["allocation_id"])["state"] == "released"


@pytest.mark.asyncio
async def test_due_leased_allocation_submits_check_job(session_factory, ledger):
    # Lease ended seconds ago — within grace, so the same cycle that
    # submits the check job must NOT force-release it.
    reserved = ledger.reserve(claim={"gpu_count": 2}, deal_ref={"escrow_uid": "0xe"})
    just_expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    ledger.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_end_utc=just_expired,
    )
    allocation = ledger.attach_lease(
        allocation_id=reserved["allocation_id"],
        vm_host="kvm1", vm_target="tenant-x",
        lease_end_utc=just_expired,
    )

    job_svc = MagicMock()
    submit = MagicMock()
    submit.job_id = "check-42"
    job_svc.submit = AsyncMock(return_value=submit)
    running = MagicMock()
    running.status = "running"
    job_svc.get_job.return_value = running

    svc = LeaseLifecycleService(
        settings=_settings(),
        capacity_ledger=ledger,
        job_service=job_svc,
    )

    import container as _container_module
    with patch.object(_container_module, "resolved_job_queue", MagicMock()):
        summary = await svc.force_check_leases()

    assert summary["checked"] == 1
    row = ledger.get_allocation(allocation["allocation_id"])
    assert row["state"] == "releasing"
    assert row["check_job_id"] == "check-42"
    params = job_svc.submit.await_args.args[0]
    assert params.vm_action == "check"
    assert params.vm_target == "tenant-x"
