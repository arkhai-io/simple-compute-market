from datetime import datetime, timezone

from core_storefront.site_resources import SiteResourcesService


class FakeLedger:
    def __init__(self):
        self.calls = []
        self.allocation = {"allocation_id": "alloc-1"}

    def list_allocations(self, *, state=None):
        self.calls.append(("list_allocations", {"state": state}))
        return [self.allocation]

    def list_lease_due(self, now):
        self.calls.append(("list_lease_due", {"now": now}))
        return [self.allocation]

    def get_allocation(self, allocation_id):
        self.calls.append(("get_allocation", {"allocation_id": allocation_id}))
        return self.allocation

    def get_allocation_by_escrow(self, escrow_uid):
        self.calls.append(("get_allocation_by_escrow", {"escrow_uid": escrow_uid}))
        return self.allocation

    def attach_lease(self, **kwargs):
        self.calls.append(("attach_lease", kwargs))
        return {**self.allocation, **kwargs}

    def update_lease_fields(self, allocation_id, **kwargs):
        self.calls.append(("update_lease_fields", {"allocation_id": allocation_id, **kwargs}))
        return {**self.allocation, **kwargs}

    def update_allocation_state(self, allocation_id, **kwargs):
        self.calls.append(("update_allocation_state", {"allocation_id": allocation_id, **kwargs}))
        return {**self.allocation, **kwargs}

    def release(self, **kwargs):
        self.calls.append(("release", kwargs))
        return {**self.allocation, **kwargs}


def test_site_resources_delegates_query_methods():
    ledger = FakeLedger()
    service = SiteResourcesService(ledger)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert service.list_allocations(state="leased") == [ledger.allocation]
    assert service.list_time_bounded_allocations_due(now) == [ledger.allocation]
    assert service.get_allocation("alloc-1") == ledger.allocation
    assert service.get_allocation_by_escrow("escrow-1") == ledger.allocation

    assert ledger.calls == [
        ("list_allocations", {"state": "leased"}),
        ("list_lease_due", {"now": now}),
        ("get_allocation", {"allocation_id": "alloc-1"}),
        ("get_allocation_by_escrow", {"escrow_uid": "escrow-1"}),
    ]


def test_site_resources_delegates_mutation_methods():
    ledger = FakeLedger()
    service = SiteResourcesService(ledger)

    attached = service.attach_lease_allocation(
        allocation_id="alloc-1",
        escrow_uid="escrow-1",
        vm_host="host-1",
        executor_kind="vm",
        executor_ref={"host_id": "host-1"},
        lease_end_utc="2026-01-01T00:00:00+00:00",
    )
    updated = service.update_allocation_fields(
        "alloc-1",
        executor_target="target-1",
        release_job_id="job-1",
    )
    state = service.update_allocation_state(
        "alloc-1",
        state="release_failed",
        failure_reason="timeout",
    )
    released = service.release_allocation("alloc-1", state="released")

    assert attached["escrow_uid"] == "escrow-1"
    assert updated["release_job_id"] == "job-1"
    assert state["failure_reason"] == "timeout"
    assert released["state"] == "released"
    assert [call[0] for call in ledger.calls] == [
        "attach_lease",
        "update_lease_fields",
        "update_allocation_state",
        "release",
    ]
