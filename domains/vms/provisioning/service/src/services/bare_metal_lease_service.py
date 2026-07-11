"""Bare-metal lease registration over site allocations."""

from __future__ import annotations

from typing import Any

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalLeaseCreate,
    PHYSICAL_HOST_ID_REF_KEY,
    bare_metal_executor_ref,
)
from core_storefront.executor_leases import (
    ExecutorLeaseRegistration,
    ExecutorLeaseService,
)
from services.lease_lifecycle_service import LeaseNotFoundError
from services.site_resources_service import SiteResourcesService


class BareMetalLeaseService:
    """Register bare-metal lease metadata on site allocations."""

    def __init__(self, site_resources_service: SiteResourcesService) -> None:
        self._leases = ExecutorLeaseService(
            site_resources_service,
            executor_kind=BARE_METAL_EXECUTOR_KIND,
            not_found_label="Bare-metal lease",
        )

    def list_leases(self) -> list[dict[str, Any]]:
        return self._leases.list_leases()

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        return self._leases.get_lease(lease_id)

    def get_lease_by_escrow(self, escrow_uid: str) -> dict[str, Any]:
        return self._leases.get_lease_by_escrow(escrow_uid)

    def register_lease(self, body: BareMetalLeaseCreate) -> dict[str, Any]:
        return self._leases.register_lease(
            ExecutorLeaseRegistration(
                allocation_id=body.allocation_id,
                escrow_uid=body.escrow_uid,
                executor_kind=BARE_METAL_EXECUTOR_KIND,
                executor_target=body.machine_id,
                executor_ref=bare_metal_executor_ref(
                    body.physical_host_id,
                    access_ref=body.access_ref,
                ),
                lease_start_utc=body.lease_start_utc,
                lease_end_utc=body.lease_end_utc,
                create_job_id=body.create_job_id,
            )
        )


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
