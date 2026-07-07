"""Bare-metal lease registration over site allocations."""

from __future__ import annotations

from typing import Any

from arkhai_bare_metal_contracts import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalLeaseCreate,
    bare_metal_executor_ref,
)
from services.lease_lifecycle_service import LeaseNotFoundError
from services.site_resources_service import SiteResourcesService


class BareMetalLeaseService:
    """Register bare-metal lease metadata on site allocations."""

    def __init__(self, site_resources_service: SiteResourcesService) -> None:
        self._site_resources = site_resources_service

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
