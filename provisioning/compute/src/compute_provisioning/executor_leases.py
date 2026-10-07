"""Lease reads over site reservations, for every offering mode.

A lease is the lifecycle tail on a site reservation: its executor target and
reference, its window, and its create and release handles. It belongs to no
offering mode of its own; the mode is the reservation's, recorded when its
capacity was claimed. A lease is addressed by its capacity reservation id. No
caller writes one: commit records its window, provisioning records its target
when the fulfillment becomes active, and the lease lifecycle records release.
"""

from __future__ import annotations

from typing import Any

from compute_provisioning.lease_lifecycle import LeaseNotFoundError
from market_site.authority import SiteAuthorityPort


def is_lease(reservation: dict[str, Any] | None) -> bool:
    """Whether a reservation carries a lease: it has a lease window's end."""

    return reservation is not None and bool(reservation.get("lease_end_utc"))


class ExecutorLeaseService:
    """List and fetch leases on site reservations."""

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


__all__ = [
    "ExecutorLeaseService",
    "is_lease",
]
