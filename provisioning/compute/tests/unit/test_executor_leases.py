from __future__ import annotations
from dataclasses import fields

from datetime import datetime, timezone

import pytest

from compute_provisioning.executor_leases import (
    ExecutorLeaseRegistration,
    ExecutorLeaseService,
    ExecutorLeaseUpdate,
    lease_datetime_value,
)
from compute_provisioning.lease_lifecycle import LeaseNotFoundError


class FakeSiteResources:
    def __init__(self) -> None:
        self.allocations = {
            "alloc-1": {
                "allocation_id": "alloc-1",
                "escrow_uid": "0x1",
                "state": "held",
            },
            "alloc-2": {
                "allocation_id": "alloc-2",
                "escrow_uid": "0x2",
                "state": "held",
                "lease_end_utc": "2099-01-01T00:00:00+00:00",
                "executor_kind": "vm",
            },
        }

    def list_allocations(self, *, state=None):
        return list(self.allocations.values())

    def get_allocation(self, allocation_id):
        return self.allocations.get(allocation_id)

    def get_allocation_by_escrow(self, escrow_uid):
        for allocation in self.allocations.values():
            if allocation.get("escrow_uid") == escrow_uid:
                return allocation
        return None

    def attach_lease_allocation(self, **kwargs):
        allocation_id = kwargs.get("allocation_id")
        if allocation_id:
            allocation = self.allocations.get(allocation_id)
        else:
            allocation = self.get_allocation_by_escrow(kwargs.get("escrow_uid"))
        if allocation is None:
            return None
        allocation.update(
            {key: value for key, value in kwargs.items() if value is not None}
        )
        allocation["state"] = "leased"
        return allocation

    def update_allocation_fields(self, allocation_id, **kwargs):
        allocation = self.allocations.get(allocation_id)
        if allocation is None:
            return None
        allocation.update(
            {key: value for key, value in kwargs.items() if value is not None}
        )
        return allocation


def test_compute_lease_metadata_is_executor_neutral():
    registration_fields = {field.name for field in fields(ExecutorLeaseRegistration)}
    update_fields = {field.name for field in fields(ExecutorLeaseUpdate)}

    assert {"executor_kind", "executor_target", "executor_ref"} <= registration_fields
    assert "vm_host" not in registration_fields
    assert "vm_target" not in registration_fields
    assert "vm_host" not in update_fields
    assert "vm_target" not in update_fields


def test_lease_datetime_value_serializes_datetimes():
    assert lease_datetime_value(
        datetime(2099, 1, 1, 0, 0, tzinfo=timezone.utc)
    ) == "2099-01-01T00:00:00+00:00"


def test_register_executor_lease_attaches_metadata():
    site = FakeSiteResources()
    service = ExecutorLeaseService(site, executor_kind="bare_metal")

    lease = service.register_lease(
        ExecutorLeaseRegistration(
            allocation_id="alloc-1",
            escrow_uid="0x1",
            executor_kind="bare_metal",
            executor_target="machine-1",
            executor_ref={"physical_host_id": "host-1"},
            lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            create_job_id="grant-1",
        )
    )

    assert lease["state"] == "leased"
    assert lease["executor_kind"] == "bare_metal"
    assert lease["executor_target"] == "machine-1"
    assert lease["create_job_id"] == "grant-1"


def test_register_executor_lease_can_attach_by_escrow():
    site = FakeSiteResources()
    service = ExecutorLeaseService(site, executor_kind="bare_metal")

    lease = service.register_lease(
        ExecutorLeaseRegistration(
            escrow_uid="0x1",
            executor_kind="bare_metal",
            executor_target="machine-1",
            lease_end_utc="2099-01-01T00:00:00+00:00",
        )
    )

    assert lease["allocation_id"] == "alloc-1"
    assert lease["executor_kind"] == "bare_metal"


def test_update_executor_lease_uses_generic_authority_fields():
    site = FakeSiteResources()
    service = ExecutorLeaseService(site, executor_kind="vm")

    updated = service.update_lease(
        "alloc-2",
        ExecutorLeaseUpdate(
            executor_target="migrated-vm",
            executor_ref={"vm_host": "kvm-2"},
            lease_end_utc=datetime(2099, 2, 1, tzinfo=timezone.utc),
            release_job_id="remove-2",
        ),
    )

    assert updated["executor_kind"] == "vm"
    assert updated["executor_target"] == "migrated-vm"
    assert updated["executor_ref"] == {"vm_host": "kvm-2"}
    assert updated["lease_end_utc"] == "2099-02-01T00:00:00+00:00"
    assert updated["release_job_id"] == "remove-2"


def test_update_executor_lease_preserves_not_found_and_kind_filter():
    service = ExecutorLeaseService(FakeSiteResources(), executor_kind="bare_metal")

    with pytest.raises(LeaseNotFoundError):
        service.update_lease(
            "alloc-2",
            ExecutorLeaseUpdate(executor_kind="vm"),
        )
    with pytest.raises(LeaseNotFoundError):
        service.update_lease("missing", ExecutorLeaseUpdate())


def test_list_and_get_leases_filter_by_executor_kind():
    service = ExecutorLeaseService(FakeSiteResources(), executor_kind="vm")

    assert [lease["allocation_id"] for lease in service.list_leases()] == ["alloc-2"]
    assert service.get_lease("alloc-2")["executor_kind"] == "vm"

    with pytest.raises(LeaseNotFoundError):
        service.get_lease("alloc-1")
