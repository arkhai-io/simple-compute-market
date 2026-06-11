"""VM lease lifecycle controller.

All endpoints are under ``/api/v1/leases``.

The storefront calls ``POST /api/v1/leases`` after provisioning a VM and
scheduling its expiry (after _do_shutdown succeeds in action_executor.py).
The LeaseWatchdog then polls the vm_leases table and calls back to the
storefront when leases expire.

Router registration
-------------------
Registered in main.py alongside the other controllers::

    app.include_router(LeasesController.make_router(), prefix="/api/v1")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_utils.cbv import cbv

import container as _container_module
from models.lease_model import (
    LeaseCreate,
    LeaseListResponse,
    LeaseResponse,
    LeaseUpdate,
)
from services.lease_service import LeaseConflictError, LeaseNotFoundError, LeaseService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leases", tags=["leases"])


@cbv(router)
class LeasesController:
    def __init__(
        self,
        lease_service: LeaseService = Depends(
            lambda: _container_module.resolved_lease_service
        ),
    ) -> None:
        self._svc = lease_service

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    @router.get(
        "/",
        response_model=LeaseListResponse,
        summary="List VM leases",
    )
    def list_leases(
        self,
        status: str | None = Query(default=None, description="Filter by LeaseStatus value."),
        vm_host: str | None = Query(default=None, description="Filter by KVM host alias."),
        escrow_uid: str | None = Query(default=None, description="Filter by on-chain escrow UID."),
    ) -> LeaseListResponse:
        """List VM leases, optionally filtered by status, host, or escrow UID."""
        leases = self._svc.list_leases(
            status=status,
            vm_host=vm_host,
            escrow_uid=escrow_uid,
        )
        return LeaseListResponse(leases=leases, total=len(leases))

    @router.post(
        "/",
        response_model=LeaseResponse,
        status_code=201,
        summary="Register a VM lease",
    )
    def create_lease(self, body: LeaseCreate, request: Request) -> LeaseResponse:
        """Register a new VM lease.

        Called by the storefront after provisioning a VM and scheduling its
        expiry. When the allocation lives in this service's capacity ledger
        (remote-capacity mode), the lease tail is recorded on the
        allocation row itself — one record, so the watchdog releases in a
        local transaction. Otherwise this falls back to the legacy
        ``vm_leases`` table, whose expiry path PATCHes the storefront's
        resource back to available.

        Returns 409 if a legacy lease for the given ``escrow_uid`` already
        exists.
        """
        ledger = _container_module.resolved_capacity_ledger_service
        if ledger is not None and body.allocation_id:
            attached = ledger.attach_lease(
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
            if attached is not None:
                logger.info(
                    "[LEASES] Attached lease to ledger allocation %s "
                    "(resource=%s escrow=%s)",
                    body.allocation_id, attached["resource_id"], body.escrow_uid,
                )
                now = datetime.now(timezone.utc)
                return LeaseResponse(
                    id=body.allocation_id,
                    resource_id=attached["resource_id"],
                    allocation_id=body.allocation_id,
                    escrow_uid=body.escrow_uid,
                    vm_host=body.vm_host,
                    vm_target=body.vm_target,
                    lease_start_utc=body.lease_start_utc,
                    lease_end_utc=body.lease_end_utc,
                    status="active",
                    create_job_id=body.create_job_id,
                    created_at=now,
                    updated_at=now,
                )

        try:
            lease = self._svc.create(body)
        except LeaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        logger.info(
            "[LEASES] Registered lease %s (resource=%s escrow=%s)",
            lease.id, lease.resource_id, lease.escrow_uid,
        )
        return lease

    # ------------------------------------------------------------------
    # By-escrow lookup (convenience — avoids needing the internal lease id)
    # ------------------------------------------------------------------

    @router.get(
        "/by-escrow/{escrow_uid}",
        response_model=LeaseResponse,
        summary="Get lease by escrow UID",
    )
    def get_lease_by_escrow(self, escrow_uid: str) -> LeaseResponse:
        """Fetch the lease for an on-chain escrow UID.

        Useful for the storefront to look up the lease it registered for a
        deal without storing the internal lease id locally.

        Returns 404 if no lease exists for this escrow UID.
        """
        lease = self._svc.get_lease_by_escrow(escrow_uid)
        if lease is None:
            raise HTTPException(
                status_code=404,
                detail=f"No lease found for escrow_uid={escrow_uid!r}",
            )
        return lease

    # ------------------------------------------------------------------
    # Instance
    # ------------------------------------------------------------------

    @router.get(
        "/{lease_id}",
        response_model=LeaseResponse,
        summary="Get a lease by ID",
    )
    def get_lease(self, lease_id: str) -> LeaseResponse:
        """Fetch a single lease by its internal ID."""
        try:
            return self._svc.get_lease(lease_id)
        except LeaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.patch(
        "/{lease_id}",
        response_model=LeaseResponse,
        summary="Partially update a lease",
    )
    def update_lease(self, lease_id: str, body: LeaseUpdate) -> LeaseResponse:
        """Partially update a lease row.

        Only non-None fields in the request body are written. Primarily used
        by operators and tests to override lease state. Normal lifecycle
        transitions happen internally via LeaseService methods called by the
        watchdog.

        Returns 404 if the lease does not exist.
        """
        try:
            return self._svc.update(lease_id, body)
        except LeaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.delete(
        "/{lease_id}/cancel",
        response_model=LeaseResponse,
        summary="Cancel an active lease before expiry",
    )
    def cancel_lease(self, lease_id: str) -> LeaseResponse:
        """Cancel a lease before it expires.

        Transitions the lease to 'cancelled'. Does NOT trigger a VM destroy
        or storefront resource release — the caller is responsible for
        submitting the appropriate Ansible jobs and patching the storefront.

        Returns 404 if the lease does not exist.
        """
        try:
            return self._svc.mark_cancelled(lease_id)
        except LeaseNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
