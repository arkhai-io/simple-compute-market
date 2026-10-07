"""Lease reads over a fake site authority.

The site's write-once rules are the ledger's and are proven against real SQLite
in ``kit/site``; this covers what the lease registry adds: which reservations
count as leases.
"""

from __future__ import annotations

import pytest

from compute_provisioning.executor_leases import ExecutorLeaseService
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

    def list_reservations(self, *, state=None):
        return list(self.reservations.values())

    def get_reservation(self, capacity_reservation_id):
        return self.reservations.get(capacity_reservation_id)


def test_the_registry_writes_no_lease():
    """Commit records a lease's window and provisioning its target at
    activation; the registry only reads."""
    assert not hasattr(ExecutorLeaseService, "register_lease")


def test_every_mode_s_leases_are_listed_and_a_hold_is_not_a_lease():
    service = ExecutorLeaseService(FakeSiteAuthority())

    assert {lease["capacity_reservation_id"] for lease in service.list_leases()} == {"vm", "bm"}
    assert service.get_lease("bm")["offering_mode"] == "bare_metal"
    with pytest.raises(LeaseNotFoundError):
        service.get_lease("hold")
