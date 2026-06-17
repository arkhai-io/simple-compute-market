"""Generic site resource/allocation adapter for provisioning services.

This adapter intentionally speaks in resource/allocation/event language rather
than lease or VM lifecycle language.  The underlying implementation still lives
in ``core_site`` today; this service is the local seam for the planned shared
SiteResourcesService boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core_site.ledger import CapacityLedgerService


class SiteResourcesService:
    """Thin adapter around the site's resource/allocation persistence service."""

    def __init__(self, capacity_service: CapacityLedgerService) -> None:
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
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Attach time-bound lease metadata to an existing allocation.

        This method is temporary compatibility glue while the lower shared
        resource layer still exposes lease-shaped persistence helpers.
        """
        return self._capacity.attach_lease(
            allocation_id=allocation_id,
            escrow_uid=escrow_uid,
            vm_host=vm_host,
            vm_target=vm_target,
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
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        vm_remove_job_id: str | None = None,
        create_job_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self._capacity.update_lease_fields(
            allocation_id,
            vm_host=vm_host,
            vm_target=vm_target,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            vm_remove_job_id=vm_remove_job_id,
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
    ) -> dict[str, Any] | None:
        return self._capacity.update_allocation_state(
            allocation_id,
            state=state,
            failure_reason=failure_reason,
            failure_message=failure_message,
            vm_remove_job_id=vm_remove_job_id,
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
