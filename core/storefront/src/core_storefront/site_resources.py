"""Shared site resource/allocation service boundary for storefront stacks."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class SiteResourceLedger(Protocol):
    """Persistence protocol used by :class:`SiteResourcesService`.

    The current implementation is supplied by ``arkhai-kit-site``. Keeping this
    as a protocol lets provisioning services share the resource/allocation seam
    without making core storefront depend on a concrete site ledger package.
    """

    def list_allocations(self, *, state: str | None = None) -> list[dict[str, Any]]: ...

    def list_lease_due(self, now: datetime) -> list[dict[str, Any]]: ...

    def get_allocation(self, allocation_id: str) -> dict[str, Any] | None: ...

    def get_allocation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None: ...

    def attach_lease(
        self,
        *,
        allocation_id: str | None = None,
        escrow_uid: str | None = None,
        vm_host: str | None = None,
        vm_target: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def update_lease_fields(
        self,
        allocation_id: str,
        *,
        vm_host: str | None = None,
        vm_target: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def update_allocation_state(
        self,
        allocation_id: str,
        *,
        state: str,
        failure_reason: str | None = None,
        failure_message: str | None = None,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
    ) -> dict[str, Any] | None: ...

    def release(
        self,
        *,
        allocation_id: str,
        state: str = "released",
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None: ...


class SiteResourcesService:
    """Thin adapter around site resource/allocation persistence."""

    def __init__(self, capacity_service: SiteResourceLedger) -> None:
        self._capacity = capacity_service

    def list_allocations(self, *, state: str | None = None) -> list[dict[str, Any]]:
        return self._capacity.list_allocations(state=state)

    def list_time_bounded_allocations_due(self, now: datetime) -> list[dict[str, Any]]:
        """Return leased/time-bounded allocations whose end time has passed."""
        return self._capacity.list_lease_due(now)

    def get_allocation(self, allocation_id: str) -> dict[str, Any] | None:
        return self._capacity.get_allocation(allocation_id)

    def get_allocation_by_escrow(self, escrow_uid: str) -> dict[str, Any] | None:
        return self._capacity.get_allocation_by_escrow(escrow_uid)

    def attach_lease_allocation(
        self,
        *,
        allocation_id: str | None = None,
        escrow_uid: str | None = None,
        vm_host: str | None = None,
        vm_target: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach time-bound lease metadata to an existing allocation."""
        return self._capacity.attach_lease(
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
        vm_host: str | None = None,
        vm_target: str | None = None,
        executor_kind: str | None = None,
        executor_target: str | None = None,
        executor_ref: dict[str, Any] | None = None,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._capacity.update_lease_fields(
            allocation_id,
            vm_host=vm_host,
            vm_target=vm_target,
            executor_kind=executor_kind,
            executor_target=executor_target,
            executor_ref=executor_ref,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            vm_remove_job_id=vm_remove_job_id,
            release_job_id=release_job_id,
            create_job_id=create_job_id,
        )

    def update_allocation_state(
        self,
        allocation_id: str,
        *,
        state: str,
        failure_reason: str | None = None,
        failure_message: str | None = None,
        vm_remove_job_id: str | None = None,
        release_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._capacity.update_allocation_state(
            allocation_id,
            state=state,
            failure_reason=failure_reason,
            failure_message=failure_message,
            vm_remove_job_id=vm_remove_job_id,
            release_job_id=release_job_id,
        )

    def release_allocation(
        self,
        allocation_id: str,
        *,
        state: str = "released",
        failure_reason: str | None = None,
        failure_message: str | None = None,
    ) -> dict[str, Any] | None:
        return self._capacity.release(
            allocation_id=allocation_id,
            state=state,
            failure_reason=failure_reason,
            failure_message=failure_message,
        )
