"""Lease registration and reads over site reservations, for every offering mode.

A lease is the lifecycle tail on a site reservation: its executor target and
reference, its window, and its create and release handles. It belongs to no
offering mode of its own; the mode is the reservation's, recorded when its
capacity was claimed. A lease is addressed by its capacity reservation id, and
registration writes its tail once (see the site ledger's ``attach_lease``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from compute_provisioning.lease_lifecycle import LeaseNotFoundError
from market_site.authority import SiteAuthorityPort


@dataclass(frozen=True)
class ExecutorLeaseRegistration:
    """The lease tail to record on a reservation."""

    capacity_reservation_id: str
    executor_target: str
    executor_ref: dict[str, Any] | None = None
    lease_start_utc: datetime | str | None = None
    lease_end_utc: datetime | str | None = None
    create_job_id: str | None = None


def lease_datetime_value(value: datetime | str | None) -> str | None:
    """Serialize common lease datetime values for the site reservation ledger."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def is_lease(reservation: dict[str, Any] | None) -> bool:
    """Whether a reservation carries a lease: it has a lease window's end."""

    return reservation is not None and bool(reservation.get("lease_end_utc"))


class ExecutorLeaseService:
    """List, fetch, and register leases on site reservations."""

    def __init__(self, site_authority: SiteAuthorityPort) -> None:
        self._site_authority = site_authority

    def list_leases(self) -> list[dict[str, Any]]:
        return [
            reservation
            for reservation in self._site_authority.list_reservations()
            if is_lease(reservation)
        ]

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        reservation = self._site_authority.get_reservation(lease_id)
        if not is_lease(reservation):
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found")
        return reservation

    def register_lease(self, registration: ExecutorLeaseRegistration) -> dict[str, Any]:
        """Record a reservation's lease tail.

        Raises ``LeaseNotFoundError`` when no live reservation has the id, and
        lets the site's ``CapacityConflictError`` through when it refuses a
        registration that would change a recorded tail or undo the lifecycle.
        """
        attached = self._site_authority.attach_lease_reservation(
            capacity_reservation_id=registration.capacity_reservation_id,
            executor_target=registration.executor_target,
            executor_ref=registration.executor_ref,
            lease_start_utc=lease_datetime_value(registration.lease_start_utc),
            lease_end_utc=lease_datetime_value(registration.lease_end_utc),
            create_job_id=registration.create_job_id,
        )
        if attached is None:
            raise LeaseNotFoundError(
                "No live reservation for capacity_reservation_id="
                f"{registration.capacity_reservation_id!r}"
            )
        return attached


__all__ = [
    "ExecutorLeaseRegistration",
    "ExecutorLeaseService",
    "is_lease",
    "lease_datetime_value",
]
