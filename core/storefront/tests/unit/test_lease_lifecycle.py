from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core_storefront.lease_lifecycle import (
    InvalidLeaseStateError,
    LeaseLifecycleService,
)


class FakeSiteResources:
    def __init__(self):
        self.allocations = {
            "alloc-1": {
                "allocation_id": "alloc-1",
                "state": "leased",
                "lease_end_utc": datetime.now(timezone.utc).isoformat(),
            }
        }
        self.due = []
        self.releasing = []

    def get_allocation(self, allocation_id):
        return self.allocations.get(allocation_id)

    def get_allocation_by_escrow(self, escrow_uid):
        for allocation in self.allocations.values():
            if allocation.get("escrow_uid") == escrow_uid:
                return allocation
        return None

    def list_allocations(self, *, state=None):
        if state == "releasing":
            return self.releasing
        return list(self.allocations.values())

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
        allocation.update({k: v for k, v in kwargs.items() if v is not None})
        return allocation

    def update_allocation_state(self, allocation_id, **kwargs):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update(kwargs)
        return allocation

    def release_allocation(self, allocation_id, **kwargs):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update(kwargs)
        allocation["released_at"] = datetime.now(timezone.utc).isoformat()
        return allocation


@pytest.mark.asyncio
async def test_terminate_lease_marks_allocation_releasing():
    site = FakeSiteResources()
    service = LeaseLifecycleService(
        SimpleNamespace(),
        site,
        release_delegate=lambda allocation: "job-1",
        default_executor_kind="vm",
    )

    updated = await service.terminate_lease("alloc-1")

    assert updated["state"] == "releasing"
    assert updated["release_job_id"] == "job-1"


@pytest.mark.asyncio
async def test_terminate_lease_rejects_invalid_state():
    site = FakeSiteResources()
    site.allocations["alloc-1"]["state"] = "release_failed"
    service = LeaseLifecycleService(
        SimpleNamespace(),
        site,
        release_delegate=lambda allocation: "job-1",
    )

    with pytest.raises(InvalidLeaseStateError) as exc_info:
        await service.terminate_lease("alloc-1")

    assert exc_info.value.state == "release_failed"


@pytest.mark.asyncio
async def test_force_check_leases_releases_direct_release_allocations():
    site = FakeSiteResources()
    allocation = {
        "allocation_id": "alloc-2",
        "state": "releasing",
        "lease_end_utc": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "release_job_id": "direct-release",
    }
    site.allocations["alloc-2"] = allocation
    site.releasing = [allocation]
    notifications = []
    service = LeaseLifecycleService(
        SimpleNamespace(lease_watchdog_grace_period_seconds=0),
        site,
        release_delegate=lambda allocation: "job-1",
        capacity_released_notifier=lambda allocation: notifications.append(allocation) or True,
    )

    result = await service.force_check_leases()

    assert result == {"checked": 0, "released": 1, "release_failed": 0, "skipped": 0}
    assert site.allocations["alloc-2"]["state"] == "released"
    assert notifications[0]["allocation_id"] == "alloc-2"
