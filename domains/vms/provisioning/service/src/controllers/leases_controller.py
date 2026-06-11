"""VM lease lifecycle controller — a view over the capacity ledger.

All endpoints are under ``/api/v1/leases``. The lease is the temporal
tail of a ledger allocation (one merged ``site_allocations`` row);
these endpoints exist for the storefront's post-provision registration
call and for operators who think in leases rather than allocations.

The storefront calls ``POST /api/v1/leases`` after provisioning a VM —
the lease tail (vm_host/vm_target/window) is recorded on the
allocation its settlement reserved. The LeaseWatchdog then drives
expiry through the ledger: teardown check job, local release, capacity
event, deal notification.

Router registration
-------------------
Registered in main.py alongside the other controllers::

    app.include_router(LeasesController.make_router(), prefix="/api/v1")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_utils.cbv import cbv

import container as _container_module
from models.lease_model import (
    LeaseCreate,
    LeaseListResponse,
    LeaseResponse,
)
from services.capacity_ledger import CapacityLedgerService, _parse_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leases", tags=["leases"])

# Allocation states surfaced in lease vocabulary.
_LEASE_STATUS = {
    "reserved": "pending",
    "provisioning": "pending",
    "leased": "active",
    "releasing": "releasing",
    "released": "released",
    "forced": "forced",
    "cancelled": "cancelled",
    "failed": "cancelled",
}


def _lease_view(allocation: dict[str, Any]) -> LeaseResponse:
    now = datetime.now(timezone.utc)
    return LeaseResponse(
        id=str(allocation["allocation_id"]),
        resource_id=str(allocation.get("resource_id") or ""),
        allocation_id=str(allocation["allocation_id"]),
        escrow_uid=str(allocation.get("escrow_uid") or ""),
        vm_host=str(allocation.get("vm_host") or ""),
        vm_target=str(allocation.get("vm_target") or ""),
        lease_start_utc=_parse_utc(allocation.get("lease_start_utc")),
        lease_end_utc=_parse_utc(allocation.get("lease_end_utc")) or now,
        status=_LEASE_STATUS.get(str(allocation.get("state")), str(allocation.get("state"))),
        create_job_id=allocation.get("create_job_id"),
        check_job_id=allocation.get("check_job_id"),
        created_at=now,
        updated_at=now,
    )


@cbv(router)
class LeasesController:
    def __init__(
        self,
        ledger: CapacityLedgerService = Depends(
            lambda: _container_module.resolved_capacity_ledger_service
        ),
    ) -> None:
        self._ledger = ledger

    @router.get(
        "/",
        response_model=LeaseListResponse,
        summary="List leases (ledger allocations with a lease tail)",
    )
    def list_leases(
        self,
        status: str | None = Query(default=None, description="Filter by lease status."),
        vm_host: str | None = Query(default=None, description="Filter by KVM host alias."),
        escrow_uid: str | None = Query(default=None, description="Filter by on-chain escrow UID."),
    ) -> LeaseListResponse:
        leases = [
            _lease_view(a)
            for a in self._ledger.list_allocations()
            if a.get("lease_end_utc")
        ]
        if status is not None:
            leases = [lease for lease in leases if lease.status == status]
        if vm_host is not None:
            leases = [lease for lease in leases if lease.vm_host == vm_host]
        if escrow_uid is not None:
            leases = [lease for lease in leases if lease.escrow_uid == escrow_uid]
        return LeaseListResponse(leases=leases, total=len(leases))

    @router.post(
        "/",
        response_model=LeaseResponse,
        status_code=201,
        summary="Register a VM lease on its allocation",
    )
    def create_lease(self, body: LeaseCreate, request: Request) -> LeaseResponse:
        """Record the lease tail on the deal's ledger allocation.

        Called by the storefront after provisioning a VM. 404 when the
        allocation isn't a live ledger row — every reservation goes
        through the ledger, so an unknown allocation means the hold
        lapsed or was already released.
        """
        attached = self._ledger.attach_lease(
            allocation_id=body.allocation_id,
            escrow_uid=body.escrow_uid,
            vm_host=body.vm_host,
            vm_target=body.vm_target,
            lease_start_utc=(
                body.lease_start_utc.isoformat() if body.lease_start_utc else None
            ),
            lease_end_utc=body.lease_end_utc.isoformat(),
            create_job_id=body.create_job_id,
        )
        if attached is None and not body.allocation_id:
            # Legacy callers registered by escrow only; the reservation
            # recorded the escrow in its deal_ref.
            attached = self._ledger.attach_lease(
                escrow_uid=body.escrow_uid,
                vm_host=body.vm_host,
                vm_target=body.vm_target,
                lease_start_utc=(
                    body.lease_start_utc.isoformat() if body.lease_start_utc else None
                ),
                lease_end_utc=body.lease_end_utc.isoformat(),
                create_job_id=body.create_job_id,
            )
        if attached is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No live ledger allocation for "
                    f"allocation_id={body.allocation_id!r} / "
                    f"escrow_uid={body.escrow_uid!r}"
                ),
            )
        logger.info(
            "[LEASES] Attached lease to allocation %s (resource=%s escrow=%s)",
            attached["allocation_id"], attached["resource_id"], body.escrow_uid,
        )
        return _lease_view(attached)

    @router.get(
        "/by-escrow/{escrow_uid}",
        response_model=LeaseResponse,
        summary="Get lease by escrow UID",
    )
    def get_lease_by_escrow(self, escrow_uid: str) -> LeaseResponse:
        """Fetch the lease for an on-chain escrow UID (404 if none)."""
        allocation = self._ledger.get_allocation_by_escrow(escrow_uid)
        if allocation is None or not allocation.get("lease_end_utc"):
            raise HTTPException(
                status_code=404,
                detail=f"No lease found for escrow_uid={escrow_uid!r}",
            )
        return _lease_view(allocation)

    @router.get(
        "/{lease_id}",
        response_model=LeaseResponse,
        summary="Get a lease by ID",
    )
    def get_lease(self, lease_id: str) -> LeaseResponse:
        """Fetch a single lease by its allocation id."""
        allocation = self._ledger.get_allocation(lease_id)
        if allocation is None:
            raise HTTPException(
                status_code=404, detail=f"Lease '{lease_id}' not found",
            )
        return _lease_view(allocation)

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
