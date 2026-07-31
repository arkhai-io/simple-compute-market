import inspect
from datetime import datetime, timezone

from market_site.authority import LedgerSiteAuthority


class FakeLedger:
    def __init__(self):
        self.calls = []
        self.reservation = {"capacity_reservation_id": "alloc-1", "deal_ref": {"listing_id": "deal-1"}}

    def list_reservations(self, *, state=None):
        self.calls.append(("list_reservations", {"state": state}))
        return [self.reservation]

    def list_lease_due(self, now):
        self.calls.append(("list_lease_due", {"now": now}))
        return [self.reservation]

    def get_reservation(self, capacity_reservation_id):
        self.calls.append(("get_reservation", {"capacity_reservation_id": capacity_reservation_id}))
        return self.reservation

    def get_reservation_by_escrow(self, escrow_uid):
        self.calls.append(("get_reservation_by_escrow", {"escrow_uid": escrow_uid}))
        return self.reservation

    def attach_lease(self, **kwargs):
        self.calls.append(("attach_lease", kwargs))
        return {**self.reservation, **kwargs}

    def update_lease_fields(self, capacity_reservation_id, **kwargs):
        self.calls.append(("update_lease_fields", {"capacity_reservation_id": capacity_reservation_id, **kwargs}))
        return {**self.reservation, **kwargs}

    def begin_releasing(self, capacity_reservation_id, **kwargs):
        self.calls.append(("begin_releasing", {"capacity_reservation_id": capacity_reservation_id, **kwargs}))
        return {**self.reservation, "state": "releasing", **kwargs}

    def update_reservation_state(self, capacity_reservation_id, **kwargs):
        self.calls.append(("update_reservation_state", {"capacity_reservation_id": capacity_reservation_id, **kwargs}))
        return {**self.reservation, **kwargs}

    def release(self, **kwargs):
        self.calls.append(("release", kwargs))
        return {**self.reservation, **kwargs}

    def events_after(self, after_version, *, limit=500):
        self.calls.append(("events_after", {"after_version": after_version, "limit": limit}))
        return ([{"version": 2, "kind": "released", "resource_id": "resource-1"}], 2)


def test_authority_delegates_reservation_queries_and_anonymous_events():
    ledger = FakeLedger()
    authority = LedgerSiteAuthority(ledger)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert authority.list_reservations(state="leased") == [ledger.reservation]
    assert authority.list_time_bounded_reservations_due(now) == [ledger.reservation]
    assert authority.get_reservation("alloc-1")["deal_ref"] == {"listing_id": "deal-1"}
    events, version = authority.capacity_events_after(1)

    assert version == 2
    assert events == [{"version": 2, "kind": "released", "resource_id": "resource-1"}]
    assert "deal_ref" not in events[0]


def test_authority_maps_generic_vm_executor_metadata_only_at_ledger_boundary():
    """CapacityReservation carries no VM-domain-specific column names --
    the adapter passes executor_kind/executor_target/executor_ref straight
    through to the ledger unchanged, with no legacy vm_host/vm_target
    synthesis. Physical placement identity (vm_host) and lease-target
    identity (vm_target) both live in the generic executor_ref/
    executor_target fields, matching bare-metal's pattern.
    """
    ledger = FakeLedger()
    authority = LedgerSiteAuthority(ledger)

    attached = authority.attach_lease_reservation(
        capacity_reservation_id="alloc-1",
        executor_kind="vm",
        executor_target="tenant-vm",
        executor_ref={"vm_host": "kvm-1"},
    )
    updated = authority.update_reservation_fields(
        "alloc-1",
        executor_kind="vm",
        executor_target="tenant-vm-2",
        executor_ref={"vm_host": "kvm-2"},
    )

    assert attached["executor_ref"]["vm_host"] == "kvm-1"
    assert attached["executor_target"] == "tenant-vm"
    assert updated["executor_ref"]["vm_host"] == "kvm-2"
    assert updated["executor_target"] == "tenant-vm-2"
    assert "vm_host" not in inspect.signature(
        authority.attach_lease_reservation
    ).parameters
    assert "vm_target" not in inspect.signature(
        authority.update_reservation_fields
    ).parameters


def test_authority_exposes_semantic_release_operations():
    ledger = FakeLedger()
    authority = LedgerSiteAuthority(ledger)

    begun = authority.begin_release("alloc-1", release_job_id="release-1")
    failed = authority.record_release_failure(
        "alloc-1", reason="executor_failed", message="teardown failed"
    )
    retried = authority.begin_release("alloc-1", release_job_id="release-2")
    released = authority.record_release_success("alloc-1")
    forced = authority.record_release_success(
        "alloc-1", forced=True, reason="admin_force_release", message="operator evidence"
    )

    assert begun["state"] == "releasing"
    assert failed["state"] == "release_failed"
    assert retried["release_job_id"] == "release-2"
    assert released["state"] == "released"
    assert forced["state"] == "force_released"
    assert [call[0] for call in ledger.calls] == [
        "begin_releasing",
        "update_reservation_state",
        "begin_releasing",
        "release",
        "release",
    ]
