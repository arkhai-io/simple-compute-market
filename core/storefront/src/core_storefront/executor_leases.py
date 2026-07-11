"""Shared executor lease registration helpers over site allocations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core_storefront.lease_lifecycle import LeaseNotFoundError
from core_storefront.site_resources import SiteResourcesService


@dataclass(frozen=True)
class ExecutorLeaseRegistration:
    """Executor-neutral lease metadata to attach to a held allocation."""

    allocation_id: str | None = None
    escrow_uid: str | None = None
    executor_kind: str | None = None
    executor_target: str | None = None
    executor_ref: dict[str, Any] | None = None
    lease_start_utc: datetime | str | None = None
    lease_end_utc: datetime | str | None = None
    create_job_id: str | None = None
    vm_host: str | None = None
    vm_target: str | None = None


def lease_datetime_value(value: datetime | str | None) -> str | None:
    """Serialize common lease datetime values for the site allocation ledger."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class ExecutorLeaseService:
    """List, fetch, and register executor leases on site allocations."""

    def __init__(
        self,
        site_resources_service: SiteResourcesService,
        *,
        executor_kind: str | None = None,
        not_found_label: str = "Lease",
    ) -> None:
        self._site_resources = site_resources_service
        self._executor_kind = executor_kind
        self._not_found_label = not_found_label

    def list_leases(self) -> list[dict[str, Any]]:
        return [
            allocation
            for allocation in self._site_resources.list_allocations()
            if allocation.get("lease_end_utc")
            and self._matches_executor_kind(allocation)
        ]

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        allocation = self._site_resources.get_allocation(lease_id)
        if (
            allocation is None
            or not allocation.get("lease_end_utc")
            or not self._matches_executor_kind(allocation)
        ):
            raise LeaseNotFoundError(f"{self._not_found_label} '{lease_id}' not found")
        return allocation

    def get_lease_by_escrow(self, escrow_uid: str) -> dict[str, Any]:
        allocation = self._site_resources.get_allocation_by_escrow(escrow_uid)
        if (
            allocation is None
            or not allocation.get("lease_end_utc")
            or not self._matches_executor_kind(allocation)
        ):
            raise LeaseNotFoundError(
                f"No {self._not_found_label.lower()} found for escrow_uid={escrow_uid!r}"
            )
        return allocation

    def register_lease(self, registration: ExecutorLeaseRegistration) -> dict[str, Any]:
        attached = self._attach_lease_allocation(registration)
        if attached is None and not registration.allocation_id:
            attached = self._attach_lease_allocation(
                ExecutorLeaseRegistration(
                    escrow_uid=registration.escrow_uid,
                    executor_kind=registration.executor_kind,
                    executor_target=registration.executor_target,
                    executor_ref=registration.executor_ref,
                    lease_start_utc=registration.lease_start_utc,
                    lease_end_utc=registration.lease_end_utc,
                    create_job_id=registration.create_job_id,
                    vm_host=registration.vm_host,
                    vm_target=registration.vm_target,
                )
            )
        if attached is None:
            raise LeaseNotFoundError(
                f"No live allocation for allocation_id={registration.allocation_id!r} / "
                f"escrow_uid={registration.escrow_uid!r}"
            )
        return attached

    def _attach_lease_allocation(
        self,
        registration: ExecutorLeaseRegistration,
    ) -> dict[str, Any] | None:
        return self._site_resources.attach_lease_allocation(
            allocation_id=registration.allocation_id,
            escrow_uid=registration.escrow_uid,
            vm_host=registration.vm_host,
            vm_target=registration.vm_target,
            executor_kind=registration.executor_kind,
            executor_target=registration.executor_target,
            executor_ref=registration.executor_ref,
            lease_start_utc=lease_datetime_value(registration.lease_start_utc),
            lease_end_utc=lease_datetime_value(registration.lease_end_utc),
            create_job_id=registration.create_job_id,
        )

    def _matches_executor_kind(self, allocation: dict[str, Any]) -> bool:
        return (
            self._executor_kind is None
            or allocation.get("executor_kind") == self._executor_kind
        )
