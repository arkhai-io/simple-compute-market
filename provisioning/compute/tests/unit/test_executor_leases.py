"""Lease registration and reads over a fake site authority.

The site's write-once rules are the ledger's and are proven against real SQLite
in ``kit/site``; this covers what the lease registry adds: which reservations
count as leases, and that registration names no offering mode and no deal.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone

import pytest

from compute_provisioning.executor_leases import (
    ExecutorLeaseRegistration,
    ExecutorLeaseService,
    lease_datetime_value,
)
from compute_provisioning.lease_lifecycle import LeaseNotFoundError


class FakeSiteAuthority:
    def __init__(self) -> None:
        self.reservations = {
            "hold": {"capacity_reservation_id": "hold", "state": "reserved"},
            "vm": {
                "capacity_reservation_id": "vm",
                "state": "leased",
                "offering_mode": "vm",
                "lease_end_utc": "2099-01-01T00:00:00+00:00",
            },
            "bm": {
                "capacity_reservation_id": "bm",
                "state": "leased",
                "offering_mode": "bare_metal",
                "lease_end_utc": "2099-01-01T00:00:00+00:00",
            },
        }
        self.attached: list[dict] = []

    def list_reservations(self, *, state=None):
        return list(self.reservations.values())

    def get_reservation(self, capacity_reservation_id):
        return self.reservations.get(capacity_reservation_id)

    def attach_lease_reservation(self, **kwargs):
        self.attached.append(kwargs)
        reservation = self.reservations.get(kwargs["capacity_reservation_id"])
        if reservation is None:
            return None
        reservation.update({key: value for key, value in kwargs.items() if value is not None})
        return reservation


def test_a_registration_names_no_offering_mode_and_no_lifecycle_evidence():
    """The mode is the reservation's, recorded when its capacity was claimed;
    the create and release handles are written by fulfillment and the lease
    lifecycle alone; and a lease is addressed by its reservation, never by a
    deal's identity."""
    names = {field.name for field in fields(ExecutorLeaseRegistration)}

    assert not {"offering_mode", "escrow_uid", "create_job_id", "release_job_id"} & names


def test_lease_datetime_value_serializes_datetimes():
    value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert lease_datetime_value(value) == value.isoformat()
    assert lease_datetime_value("2026-01-01 00:00") == "2026-01-01 00:00"
    assert lease_datetime_value(None) is None


def test_registration_passes_the_tail_to_the_site():
    site = FakeSiteAuthority()

    attached = ExecutorLeaseService(site).register_lease(
        ExecutorLeaseRegistration(
            capacity_reservation_id="vm",
            executor_target="tenant-1",
            lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
            deal_ref={"escrow_uid": "0x1"},
        )
    )

    assert attached["executor_target"] == "tenant-1"
    assert site.attached[0]["lease_end_utc"] == "2099-01-01T00:00:00+00:00"
    assert site.attached[0]["deal_ref"] == {"escrow_uid": "0x1"}


def test_registration_on_no_live_reservation_is_not_found():
    with pytest.raises(LeaseNotFoundError):
        ExecutorLeaseService(FakeSiteAuthority()).register_lease(
            ExecutorLeaseRegistration(capacity_reservation_id="missing", executor_target="t")
        )


def test_every_mode_s_leases_are_listed_and_a_hold_is_not_a_lease():
    service = ExecutorLeaseService(FakeSiteAuthority())

    assert {lease["capacity_reservation_id"] for lease in service.list_leases()} == {"vm", "bm"}
    assert service.get_lease("bm")["offering_mode"] == "bare_metal"
    with pytest.raises(LeaseNotFoundError):
        service.get_lease("hold")
