"""Bare-metal lease registration over site allocations."""

from __future__ import annotations

from typing import Any

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalLeaseCreate,
    PHYSICAL_HOST_ID_REF_KEY,
    bare_metal_executor_ref,
)
from services.lease_lifecycle_service import LeaseNotFoundError
from services.site_resources_service import SiteResourcesService


class BareMetalLeaseService:
    """Register bare-metal lease metadata on site allocations."""

    def __init__(self, site_resources_service: SiteResourcesService) -> None:
        self._site_resources = site_resources_service

    def list_leases(self) -> list[dict[str, Any]]:
        return [
            allocation
            for allocation in self._site_resources.list_allocations()
            if allocation.get("lease_end_utc")
            and allocation.get("executor_kind") == BARE_METAL_EXECUTOR_KIND
        ]

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        allocation = self._site_resources.get_allocation(lease_id)
        if (
            allocation is None
            or not allocation.get("lease_end_utc")
            or allocation.get("executor_kind") != BARE_METAL_EXECUTOR_KIND
        ):
            raise LeaseNotFoundError(f"Bare-metal lease '{lease_id}' not found")
        return allocation

    def get_lease_by_escrow(self, escrow_uid: str) -> dict[str, Any]:
        allocation = self._site_resources.get_allocation_by_escrow(escrow_uid)
        if (
            allocation is None
            or not allocation.get("lease_end_utc")
            or allocation.get("executor_kind") != BARE_METAL_EXECUTOR_KIND
        ):
            raise LeaseNotFoundError(
                f"No bare-metal lease found for escrow_uid={escrow_uid!r}"
            )
        return allocation

    def register_lease(self, body: BareMetalLeaseCreate) -> dict[str, Any]:
        attached = self._site_resources.attach_lease_allocation(
            allocation_id=body.allocation_id,
            escrow_uid=body.escrow_uid,
            executor_kind=BARE_METAL_EXECUTOR_KIND,
            executor_target=body.machine_id,
            executor_ref=bare_metal_executor_ref(
                body.physical_host_id,
                access_ref=body.access_ref,
            ),
            lease_start_utc=(
                body.lease_start_utc.isoformat() if body.lease_start_utc else None
            ),
            lease_end_utc=body.lease_end_utc.isoformat(),
            create_job_id=body.create_job_id,
        )
        if attached is None and not body.allocation_id:
            attached = self._site_resources.attach_lease_allocation(
                escrow_uid=body.escrow_uid,
                executor_kind=BARE_METAL_EXECUTOR_KIND,
                executor_target=body.machine_id,
                executor_ref=bare_metal_executor_ref(
                    body.physical_host_id,
                    access_ref=body.access_ref,
                ),
                lease_start_utc=(
                    body.lease_start_utc.isoformat() if body.lease_start_utc else None
                ),
                lease_end_utc=body.lease_end_utc.isoformat(),
                create_job_id=body.create_job_id,
            )
        if attached is None:
            raise LeaseNotFoundError(
                f"No live allocation for allocation_id={body.allocation_id!r} / "
                f"escrow_uid={body.escrow_uid!r}"
            )
        return attached


def bare_metal_access_ref(allocation: dict[str, Any]) -> dict[str, Any] | None:
    executor_ref = allocation.get("executor_ref")
    if not isinstance(executor_ref, dict):
        return None
    access_ref = {
        key: value
        for key, value in executor_ref.items()
        if key != PHYSICAL_HOST_ID_REF_KEY
    }
    return access_ref or None
