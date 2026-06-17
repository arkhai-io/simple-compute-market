"""VM lease lifecycle controller.

The controller owns HTTP concerns only. Lease lifecycle state transitions are
implemented by ``LeaseLifecycleService``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

import container as _container_module
from core_site.ledger import parse_utc as _parse_utc
from models.lease_model import (
    LeaseCreate,
    LeaseForceReleaseRequest,
    LeaseListResponse,
    LeaseReleaseOversightRequest,
    LeaseResponse,
    LeaseRetryReleaseRequest,
    LeaseTerminateRequest,
    LeaseUpdate,
)
from services.lease_lifecycle_service import (
    InvalidLeaseStateError,
    LeaseLifecycleError,
    LeaseLifecycleService,
    LeaseNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leases", tags=["leases"])
admin_router = APIRouter(prefix="/admin/leases", tags=["admin", "leases"])

_LEASE_STATUS = {
    "reserved": "pending",
    "provisioning": "pending",
    "leased": "active",
    "releasing": "releasing",
    "released": "released",
    "release_failed": "release_failed",
    "unmanaged": "unmanaged",
    "provisioning_failed": "provisioning_failed",
    "force_released": "force_released",
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
        vm_remove_job_id=allocation.get("vm_remove_job_id"),
        created_at=now,
        updated_at=now,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LeaseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, InvalidLeaseStateError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@cbv(router)
class LeasesController:
    def __init__(
        self,
        lease_lifecycle_service: LeaseLifecycleService = Depends(
            lambda: _container_module.resolved_lease_lifecycle_service
        ),
    ) -> None:
        self._leases = lease_lifecycle_service

    @router.get(
        "/",
        response_model=LeaseListResponse,
        summary="List leases",
    )
    def list_leases(
        self,
        status: str | None = Query(default=None, description="Filter by lease status."),
        vm_host: str | None = Query(default=None, description="Filter by KVM host alias."),
        escrow_uid: str | None = Query(default=None, description="Filter by on-chain escrow UID."),
    ) -> LeaseListResponse:
        leases = [_lease_view(a) for a in self._leases.list_leases()]
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
    def create_lease(self, body: LeaseCreate) -> LeaseResponse:
        try:
            attached = self._leases.register_lease(body)
        except LeaseNotFoundError as exc:
            raise _http_error(exc) from exc
        logger.info(
            "[LEASES] Attached lease to allocation %s (resource=%s escrow=%s)",
            attached["allocation_id"], attached.get("resource_id"), body.escrow_uid,
        )
        return _lease_view(attached)

    @router.get(
        "/by-escrow/{escrow_uid}",
        response_model=LeaseResponse,
        summary="Get lease by escrow UID",
    )
    def get_lease_by_escrow(self, escrow_uid: str) -> LeaseResponse:
        try:
            return _lease_view(self._leases.get_lease_by_escrow(escrow_uid))
        except LeaseNotFoundError as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/{lease_id}",
        response_model=LeaseResponse,
        summary="Get a lease by ID",
    )
    def get_lease(self, lease_id: str) -> LeaseResponse:
        try:
            return _lease_view(self._leases.get_lease(lease_id))
        except LeaseNotFoundError as exc:
            raise _http_error(exc) from exc

    @router.patch(
        "/{lease_id}",
        response_model=LeaseResponse,
        summary="Partial-update lease fields",
    )
    def update_lease(self, lease_id: str, body: LeaseUpdate) -> LeaseResponse:
        try:
            updated = self._leases.update_lease(lease_id, body)
        except LeaseLifecycleError as exc:
            raise _http_error(exc) from exc
        logger.info("[LEASES] Updated fields on allocation %s", lease_id)
        return _lease_view(updated)

    @router.post(
        "/{lease_id}/terminate",
        response_model=LeaseResponse,
        summary="Terminate a market-managed lease",
        description=(
            "Submits the lease release operation for this provisioning service "
            "(vm_remove for VM leases) and moves the lease to releasing. "
            "Capacity is released only after vm_remove succeeds. Failed, "
            "cancelled, or timed-out teardown leaves the lease in release_failed."
        ),
    )
    async def terminate_lease(
        self, lease_id: str, body: LeaseTerminateRequest | None = None,
    ) -> LeaseResponse:
        try:
            allocation = await self._leases.terminate_lease(
                lease_id, body or LeaseTerminateRequest(),
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(allocation)

    @router.post(
        "/{lease_id}/release-oversight",
        response_model=LeaseResponse,
        summary="Release lifecycle oversight without releasing capacity",
        description=(
            "Moves a leased allocation to unmanaged. This does not delete the VM, "
            "does not submit vm_remove, and does not release capacity. An admin "
            "must later clean up the workload and force-release capacity."
        ),
    )
    def release_oversight(
        self, lease_id: str, body: LeaseReleaseOversightRequest,
    ) -> LeaseResponse:
        try:
            allocation = self._leases.release_oversight(lease_id, body)
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(allocation)

    @classmethod
    def make_router(cls) -> APIRouter:
        return router


@cbv(admin_router)
class AdminLeasesController:
    def __init__(
        self,
        lease_lifecycle_service: LeaseLifecycleService = Depends(
            lambda: _container_module.resolved_lease_lifecycle_service
        ),
    ) -> None:
        self._leases = lease_lifecycle_service

    @admin_router.post(
        "/{lease_id}/retry-release",
        response_model=LeaseResponse,
        summary="Retry a failed lease release",
        description=(
            "Admin repair action for release_failed leases. Submits the service's "
            "release delegate again (vm_remove for VM leases), returns the lease to "
            "releasing, and keeps capacity held until the retry succeeds."
        ),
    )
    async def retry_release(
        self, lease_id: str, body: LeaseRetryReleaseRequest | None = None,
    ) -> LeaseResponse:
        try:
            allocation = await self._leases.retry_release(
                lease_id, body or LeaseRetryReleaseRequest(),
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(allocation)

    @admin_router.post(
        "/{lease_id}/force-release",
        response_model=LeaseResponse,
        summary="Force-release lease capacity",
        description=(
            "Admin-only repair action. Releases capacity without teardown proof and "
            "moves the lease to force_released. Use only after manual verification "
            "that capacity is safe to resell."
        ),
    )
    async def force_release(
        self, lease_id: str, body: LeaseForceReleaseRequest,
    ) -> LeaseResponse:
        try:
            allocation = await self._leases.force_release(lease_id, body)
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(allocation)

    @classmethod
    def make_router(cls) -> APIRouter:
        return admin_router
