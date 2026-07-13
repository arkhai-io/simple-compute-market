"""Executor-neutral site authority port and ledger adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class SiteAuthorityPort(Protocol):
    """Allocation lifecycle facts consumed by compute orchestration."""

    def list_allocations(self, *, state: str | None = None) -> list[dict[str, Any]]: ...

    def list_time_bounded_allocations_due(self, now: datetime) -> list[dict[str, Any]]: ...

    def get_allocation(self, allocation_id: str) -> dict[str, Any] | None: ...

    def get_allocation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None: ...

    def attach_lease_allocation(
        self,
        *,
        allocation_id: str | None = None,
        escrow_uid: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def update_allocation_fields(
        self,
        allocation_id: str,
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
        self, allocation_id: str, *, release_job_id: str
    ) -> dict[str, Any] | None: ...

    def record_release_failure(
        self,
        allocation_id: str,
        *,
        reason: str,
        message: str | None = None,
    ) -> dict[str, Any] | None: ...

    def record_release_success(
        self,
        allocation_id: str,
        *,
        forced: bool = False,
        reason: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any] | None: ...

    def record_unmanaged(
        self, allocation_id: str, *, reason: str, message: str | None = None
    ) -> dict[str, Any] | None: ...

    def capacity_events_after(
        self, after_version: int, *, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]: ...


class SiteAuthorityLedger(Protocol):
    """Persistence operations supplied by the site ledger."""

    def list_allocations(self, *, state: str | None = None) -> list[dict[str, Any]]: ...

    def list_lease_due(self, now: datetime) -> list[dict[str, Any]]: ...

    def get_allocation(self, allocation_id: str) -> dict[str, Any] | None: ...

    def get_allocation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None: ...

    def attach_lease(self, **fields: Any) -> dict[str, Any] | None: ...

    def update_lease_fields(
        self, allocation_id: str, **fields: Any
    ) -> dict[str, Any] | None: ...

    def begin_releasing(
        self, allocation_id: str, *, release_job_id: str | None = None
    ) -> dict[str, Any] | None: ...

    def update_allocation_state(
        self,
        allocation_id: str,
        *,
        state: str,
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None: ...

    def release(
        self,
        *,
        allocation_id: str,
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

    def list_allocations(self, *, state: str | None = None) -> list[dict[str, Any]]:
        return self._ledger.list_allocations(state=state)

    def list_time_bounded_allocations_due(self, now: datetime) -> list[dict[str, Any]]:
        return self._ledger.list_lease_due(now)

    def get_allocation(self, allocation_id: str) -> dict[str, Any] | None:
        return self._ledger.get_allocation(allocation_id)

    def get_allocation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None:
        return self._ledger.get_allocation_by_escrow(escrow_uid)

    def attach_lease_allocation(
        self,
        *,
        allocation_id: str | None = None,
        escrow_uid: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        vm_host, vm_target = self._legacy_vm_fields(
            executor_kind, executor_target, executor_ref
        )
        return self._ledger.attach_lease(
            allocation_id=allocation_id,
            escrow_uid=escrow_uid,
            vm_host=vm_host,
            vm_target=vm_target,
            executor_kind=executor_kind,
            executor_target=executor_target,
            executor_ref=executor_ref,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            create_job_id=create_job_id,
        )

    def update_allocation_fields(
        self,
        allocation_id: str,
        *,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        release_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        vm_host, vm_target = self._legacy_vm_fields(
            executor_kind, executor_target, executor_ref
        )
        return self._ledger.update_lease_fields(
            allocation_id,
            vm_host=vm_host,
            vm_target=vm_target,
            executor_kind=executor_kind,
            executor_target=executor_target,
            executor_ref=executor_ref,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            release_job_id=release_job_id,
            create_job_id=create_job_id,
        )

    @staticmethod
    def _legacy_vm_fields(
        executor_kind: str | None,
        executor_target: str | None,
        executor_ref: dict[str, Any] | None,
    ) -> tuple[str | None, str | None]:
        if executor_kind != "vm":
            return None, None
        executor_ref = executor_ref or {}
        vm_host = executor_ref.get("vm_host")
        return (str(vm_host) if vm_host else None, executor_target)

    def begin_release(
        self, allocation_id: str, *, release_job_id: str
    ) -> dict[str, Any] | None:
        return self._ledger.begin_releasing(
            allocation_id, release_job_id=release_job_id
        )

    def record_release_failure(
        self,
        allocation_id: str,
        *,
        reason: str,
        message: str | None = None,
    ) -> dict[str, Any] | None:
        return self._ledger.update_allocation_state(
            allocation_id,
            state="release_failed",
            failure_reason=reason,
            failure_message=message,
        )

    def record_release_success(
        self,
        allocation_id: str,
        *,
        forced: bool = False,
        reason: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any] | None:
        return self._ledger.release(
            allocation_id=allocation_id,
            state="force_released" if forced else "released",
            failure_reason=reason,
            failure_message=message,
        )

    def record_unmanaged(
        self, allocation_id: str, *, reason: str, message: str | None = None
    ) -> dict[str, Any] | None:
        return self._ledger.update_allocation_state(
            allocation_id,
            state="unmanaged",
            failure_reason=reason,
            failure_message=message,
        )

    def capacity_events_after(
        self, after_version: int, *, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        return self._ledger.events_after(after_version, limit=limit)
