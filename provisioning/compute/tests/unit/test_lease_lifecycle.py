from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from compute_provisioning.lease_lifecycle import (
    InvalidLeaseStateError,
    LeaseLifecycleService,
)


class FakeSiteAuthority:
    def __init__(self):
        self.allocations = {
            "alloc-1": {
                "allocation_id": "alloc-1",
                "state": "leased",
                "lease_end_utc": datetime.now(timezone.utc).isoformat(),
            }
        }
        self.due = []

    def get_allocation(self, allocation_id):
        return self.allocations.get(allocation_id)

    def get_allocation_by_escrow(self, escrow_uid):
        return next(
            (a for a in self.allocations.values() if a.get("escrow_uid") == escrow_uid),
            None,
        )

    def list_allocations(self, *, state=None):
        values = list(self.allocations.values())
        return [a for a in values if state is None or a["state"] == state]

    def list_time_bounded_allocations_due(self, now):
        return self.due

    def attach_lease_allocation(self, **kwargs):
        allocation = {"allocation_id": kwargs.get("allocation_id") or "alloc-new", **kwargs}
        self.allocations[allocation["allocation_id"]] = allocation
        return allocation

    def update_allocation_fields(self, allocation_id, **kwargs):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update({key: value for key, value in kwargs.items() if value is not None})
        return allocation

    def begin_release(self, allocation_id, *, release_job_id):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update(state="releasing", release_job_id=release_job_id)
        return allocation

    def record_release_failure(self, allocation_id, *, reason, message=None):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update(
            state="release_failed", failure_reason=reason, failure_message=message
        )
        return allocation

    def record_release_success(
        self, allocation_id, *, forced=False, reason=None, message=None
    ):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update(
            state="force_released" if forced else "released",
            failure_reason=reason,
            failure_message=message,
            released_at=datetime.now(timezone.utc).isoformat(),
        )
        return allocation

    def record_unmanaged(self, allocation_id, *, reason, message=None):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update(state="unmanaged", failure_reason=reason, failure_message=message)
        return allocation


class StubExecutorRelease:
    def __init__(self, job_id="job-1"):
        self.job_id = job_id
        self.calls = []

    async def submit_release(self, allocation):
        self.calls.append(allocation["allocation_id"])
        return self.job_id


@pytest.mark.asyncio
async def test_terminate_lease_uses_injected_ports_and_keeps_capacity_held():
    site = FakeSiteAuthority()
    executor = StubExecutorRelease()
    service = LeaseLifecycleService(
        SimpleNamespace(), site, executor_release=executor, default_executor_kind="vm"
    )

    updated = await service.terminate_lease("alloc-1")

    assert updated["state"] == "releasing"
    assert updated["release_job_id"] == "job-1"
    assert updated.get("released_at") is None
    assert executor.calls == ["alloc-1"]


@pytest.mark.asyncio
async def test_terminate_lease_rejects_failed_state_until_retry_or_force():
    site = FakeSiteAuthority()
    site.allocations["alloc-1"]["state"] = "release_failed"
    service = LeaseLifecycleService(
        SimpleNamespace(), site, executor_release=StubExecutorRelease()
    )

    with pytest.raises(InvalidLeaseStateError) as exc_info:
        await service.terminate_lease("alloc-1")

    assert exc_info.value.state == "release_failed"


@pytest.mark.asyncio
async def test_direct_release_commits_once_then_notifies_deal_sink():
    site = FakeSiteAuthority()
    allocation = {
        "allocation_id": "alloc-2",
        "state": "releasing",
        "lease_end_utc": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "release_job_id": "direct-release",
        "deal_ref": {"listing_id": "deal-2"},
    }
    site.allocations["alloc-2"] = allocation
    notifications = []
    service = LeaseLifecycleService(
        SimpleNamespace(lease_watchdog_grace_period_seconds=0),
        site,
        executor_release=StubExecutorRelease(),
        capacity_released_notifier=lambda value: notifications.append(value) or True,
    )

    first = await service.force_check_leases()
    second = await service.force_check_leases()

    assert first == {"checked": 0, "released": 1, "release_failed": 0, "skipped": 0}
    assert second == {"checked": 0, "released": 0, "release_failed": 0, "skipped": 0}
    assert site.allocations["alloc-2"]["state"] == "released"
    assert notifications == [site.allocations["alloc-2"]]
    assert notifications[0]["deal_ref"] == {"listing_id": "deal-2"}


@pytest.mark.asyncio
async def test_failed_executor_submission_holds_capacity_until_force_release():
    site = FakeSiteAuthority()
    allocation = site.allocations["alloc-1"]
    site.due = [allocation]
    service = LeaseLifecycleService(
        SimpleNamespace(), site, executor_release=StubExecutorRelease(job_id=None)
    )

    result = await service.force_check_leases()

    assert result["release_failed"] == 1
    assert allocation["state"] == "release_failed"
    assert "released_at" not in allocation

    forced = await service.force_release(
        "alloc-1", SimpleNamespace(reason="executor unreachable", evidence="ticket-7")
    )
    assert forced["state"] == "force_released"
    assert forced["failure_reason"] == "admin_force_release"
    assert "ticket-7" in forced["failure_message"]
