"""Executor-neutral site authority port and ledger adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class SiteAuthorityPort(Protocol):
    """Reservation lifecycle facts consumed by compute orchestration."""

    def list_reservations(self, *, state: str | None = None) -> list[dict[str, Any]]: ...

    def list_time_bounded_reservations_due(self, now: datetime) -> list[dict[str, Any]]: ...

    def get_reservation(self, capacity_reservation_id: str) -> dict[str, Any] | None: ...

    def get_reservation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None: ...

    def attach_lease_reservation(
        self,
        *,
        capacity_reservation_id: str | None = None,
        escrow_uid: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def update_reservation_fields(
        self,
        capacity_reservation_id: str,
        *,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        release_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def begin_release(
        self, capacity_reservation_id: str, *, release_job_id: str
    ) -> dict[str, Any] | None: ...

    def record_release_failure(
        self,
        capacity_reservation_id: str,
        *,
        reason: str,
        message: str | None = None,
    ) -> dict[str, Any] | None: ...

    def record_release_success(
        self,
        capacity_reservation_id: str,
        *,
        forced: bool = False,
        reason: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any] | None: ...

    def record_unmanaged(
        self, capacity_reservation_id: str, *, reason: str, message: str | None = None
    ) -> dict[str, Any] | None: ...

    def capacity_events_after(
        self, after_version: int, *, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]: ...


class SiteAuthorityLedger(Protocol):
    """Persistence operations supplied by the site ledger."""

    def list_reservations(self, *, state: str | None = None) -> list[dict[str, Any]]: ...

    def list_lease_due(self, now: datetime) -> list[dict[str, Any]]: ...

    def get_reservation(self, capacity_reservation_id: str) -> dict[str, Any] | None: ...

    def get_reservation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None: ...

    def attach_lease(self, **fields: Any) -> dict[str, Any] | None: ...

    def update_lease_fields(
        self, capacity_reservation_id: str, **fields: Any
    ) -> dict[str, Any] | None: ...

    def begin_releasing(
        self, capacity_reservation_id: str, *, release_job_id: str | None = None
    ) -> dict[str, Any] | None: ...

    def update_reservation_state(
        self,
        capacity_reservation_id: str,
        *,
        state: str,
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None: ...

    def release(
        self,
        *,
        capacity_reservation_id: str,
        state: str = "released",
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None: ...

    def events_after(
        self, after_version: int, *, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]: ...


class LedgerSiteAuthority:
    """Adapt the transactional site ledger to :class:`SiteAuthorityPort`."""

    def __init__(self, ledger: SiteAuthorityLedger) -> None:
        self._ledger = ledger

    def list_reservations(self, *, state: str | None = None) -> list[dict[str, Any]]:
        return self._ledger.list_reservations(state=state)

    def list_time_bounded_reservations_due(self, now: datetime) -> list[dict[str, Any]]:
        return self._ledger.list_lease_due(now)

    def get_reservation(self, capacity_reservation_id: str) -> dict[str, Any] | None:
        return self._ledger.get_reservation(capacity_reservation_id)

    def get_reservation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None:
        return self._ledger.get_reservation_by_escrow(escrow_uid)

    def attach_lease_reservation(
        self,
        *,
        capacity_reservation_id: str | None = None,
        escrow_uid: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._ledger.attach_lease(
            capacity_reservation_id=capacity_reservation_id,
            escrow_uid=escrow_uid,
            executor_kind=executor_kind,
            executor_target=executor_target,
            executor_ref=executor_ref,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            create_job_id=create_job_id,
        )

    def update_reservation_fields(
        self,
        capacity_reservation_id: str,
        *,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        release_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._ledger.update_lease_fields(
            capacity_reservation_id,
            executor_kind=executor_kind,
            executor_target=executor_target,
            executor_ref=executor_ref,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            release_job_id=release_job_id,
            create_job_id=create_job_id,
        )

    def begin_release(
        self, capacity_reservation_id: str, *, release_job_id: str
    ) -> dict[str, Any] | None:
        return self._ledger.begin_releasing(
            capacity_reservation_id, release_job_id=release_job_id
        )

    def record_release_failure(
        self,
        capacity_reservation_id: str,
        *,
        reason: str,
        message: str | None = None,
    ) -> dict[str, Any] | None:
        return self._ledger.update_reservation_state(
            capacity_reservation_id,
            state="release_failed",
            failure_reason=reason,
            failure_message=message,
        )

    def record_release_success(
        self,
        capacity_reservation_id: str,
        *,
        forced: bool = False,
        reason: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any] | None:
        return self._ledger.release(
            capacity_reservation_id=capacity_reservation_id,
            state="force_released" if forced else "released",
            failure_reason=reason,
            failure_message=message,
        )

    def record_unmanaged(
        self, capacity_reservation_id: str, *, reason: str, message: str | None = None
    ) -> dict[str, Any] | None:
        return self._ledger.update_reservation_state(
            capacity_reservation_id,
            state="unmanaged",
            failure_reason=reason,
            failure_message=message,
        )

    def capacity_events_after(
        self, after_version: int, *, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        return self._ledger.events_after(after_version, limit=limit)
