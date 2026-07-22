"""Bare-metal lease registration over site reservations."""

from __future__ import annotations

from typing import Any

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalLeaseCreate,
    PHYSICAL_HOST_ID_REF_KEY,
    bare_metal_executor_ref,
)
from compute_provisioning.executor_leases import (
    ExecutorLeaseRegistration,
    ExecutorLeaseService,
)
from market_site.authority import SiteAuthorityPort


class BareMetalLeaseService:
    """Register bare-metal lease metadata on site reservations."""

    def __init__(self, site_authority: SiteAuthorityPort) -> None:
        self._leases = ExecutorLeaseService(
            site_authority,
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
                capacity_reservation_id=body.capacity_reservation_id,
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


def bare_metal_access_ref(reservation: dict[str, Any]) -> dict[str, Any] | None:
    executor_ref = reservation.get("executor_ref")
    if not isinstance(executor_ref, dict):
        return None
    access_ref = {
        key: value
        for key, value in executor_ref.items()
        if key != PHYSICAL_HOST_ID_REF_KEY
    }
    return access_ref or None
