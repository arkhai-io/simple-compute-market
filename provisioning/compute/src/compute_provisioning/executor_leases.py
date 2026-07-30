"""Shared executor lease registration helpers over site reservations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from compute_provisioning.lease_lifecycle import LeaseNotFoundError
from market_site.authority import SiteAuthorityPort


@dataclass(frozen=True)
class ExecutorLeaseRegistration:
    """Executor-neutral lease metadata to attach to a held reservation."""

    capacity_reservation_id: str | None = None
    escrow_uid: str | None = None
    executor_kind: str | None = None
    executor_target: str | None = None
    executor_ref: dict[str, Any] | None = None
    lease_start_utc: datetime | str | None = None
    lease_end_utc: datetime | str | None = None
    create_job_id: str | None = None


@dataclass(frozen=True)
class ExecutorLeaseUpdate:
    """Executor-neutral mutable lease-tail metadata."""

    executor_kind: str | None = None
    executor_target: str | None = None
    executor_ref: dict[str, Any] | None = None
    lease_start_utc: datetime | str | None = None
    lease_end_utc: datetime | str | None = None
    release_job_id: str | None = None
    create_job_id: str | None = None


def lease_datetime_value(value: datetime | str | None) -> str | None:
    """Serialize common lease datetime values for the site reservation ledger."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class ExecutorLeaseService:
    """List, fetch, and register executor leases on site reservations."""

    def __init__(
        self,
        site_authority: SiteAuthorityPort,
        *,
        executor_kind: str | None = None,
        not_found_label: str = "Lease",
    ) -> None:
        self._site_authority = site_authority
        self._executor_kind = executor_kind
        self._not_found_label = not_found_label

    def list_leases(self) -> list[dict[str, Any]]:
        return [
            reservation
            for reservation in self._site_authority.list_reservations()
            if reservation.get("lease_end_utc")
            and self._matches_executor_kind(reservation)
        ]

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        reservation = self._site_authority.get_reservation(lease_id)
        if (
            reservation is None
            or not reservation.get("lease_end_utc")
            or not self._matches_executor_kind(reservation)
        ):
            raise LeaseNotFoundError(f"{self._not_found_label} '{lease_id}' not found")
        return reservation

    def get_lease_by_escrow(self, escrow_uid: str) -> dict[str, Any]:
        reservation = self._site_authority.get_reservation_by_escrow(escrow_uid)
        if (
            reservation is None
            or not reservation.get("lease_end_utc")
            or not self._matches_executor_kind(reservation)
        ):
            raise LeaseNotFoundError(
                f"No {self._not_found_label.lower()} found for escrow_uid={escrow_uid!r}"
            )
        return reservation

    def register_lease(self, registration: ExecutorLeaseRegistration) -> dict[str, Any]:
        attached = self._attach_lease_reservation(registration)
        if attached is None and not registration.capacity_reservation_id:
            attached = self._attach_lease_reservation(
                ExecutorLeaseRegistration(
                    escrow_uid=registration.escrow_uid,
                    executor_kind=registration.executor_kind,
                    executor_target=registration.executor_target,
                    executor_ref=registration.executor_ref,
                    lease_start_utc=registration.lease_start_utc,
                    lease_end_utc=registration.lease_end_utc,
                    create_job_id=registration.create_job_id,
                )
            )
        if attached is None:
            raise LeaseNotFoundError(
                f"No live reservation for capacity_reservation_id={registration.capacity_reservation_id!r} / "
                f"escrow_uid={registration.escrow_uid!r}"
            )
        return attached

    def update_lease(
        self,
        lease_id: str,
        update: ExecutorLeaseUpdate,
    ) -> dict[str, Any]:
        """Update generic lease-tail metadata for this executor kind."""
        self.get_lease(lease_id)
        executor_kind = update.executor_kind or self._executor_kind
        if (
            self._executor_kind is not None
            and executor_kind is not None
            and executor_kind != self._executor_kind
        ):
            raise LeaseNotFoundError(
                f"{self._not_found_label} '{lease_id}' not found"
            )
        updated = self._site_authority.update_reservation_fields(
            lease_id,
            executor_kind=executor_kind,
            executor_target=update.executor_target,
            executor_ref=update.executor_ref,
            lease_start_utc=lease_datetime_value(update.lease_start_utc),
            lease_end_utc=lease_datetime_value(update.lease_end_utc),
            release_job_id=update.release_job_id,
            create_job_id=update.create_job_id,
        )
        if updated is None or not self._matches_executor_kind(updated):
            raise LeaseNotFoundError(
                f"{self._not_found_label} '{lease_id}' not found or terminal"
            )
        return updated

    def _attach_lease_reservation(
        self,
        registration: ExecutorLeaseRegistration,
    ) -> dict[str, Any] | None:
        return self._site_authority.attach_lease_reservation(
            capacity_reservation_id=registration.capacity_reservation_id,
            escrow_uid=registration.escrow_uid,
            executor_kind=registration.executor_kind,
            executor_target=registration.executor_target,
            executor_ref=registration.executor_ref,
            lease_start_utc=lease_datetime_value(registration.lease_start_utc),
            lease_end_utc=lease_datetime_value(registration.lease_end_utc),
            create_job_id=registration.create_job_id,
        )

    def _matches_executor_kind(self, reservation: dict[str, Any]) -> bool:
        return (
            self._executor_kind is None
            or reservation.get("executor_kind") == self._executor_kind
        )
