"""Market-managed lease lifecycle controller.

The controller owns HTTP concerns only. Lease lifecycle state transitions are
implemented by ``LeaseLifecycleService``. VM-shaped lease creation remains here
for the current VM domain adapter; release operations are executor-dispatched
and are not tied to the direct ``/hosts/{host}/vms`` operator API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_utils.cbv import cbv

from compute_provisioning_service import container as _container_module
from compute_provisioning import lease_state_for_reservation_state
from market_site.ledger import parse_utc as _parse_utc
from vm_provisioning_operator.models import (
    LeaseCreate,
    LeaseForceReleaseRequest,
    LeaseListResponse,
    LeaseReleaseOversightRequest,
    LeaseResponse,
    LeaseRetryReleaseRequest,
    LeaseTerminateRequest,
    LeaseUpdate,
)
from compute_provisioning.executor_leases import (
    ExecutorLeaseRegistration,
    ExecutorLeaseUpdate,
)
from compute_provisioning.lease_lifecycle import (
    InvalidLeaseStateError,
    LeaseLifecycleError,
    LeaseLifecycleService,
    LeaseNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leases", tags=["leases"])
admin_router = APIRouter(prefix="/admin/leases", tags=["admin", "leases"])
_VM_EXECUTOR_KIND = "vm"


def _lease_view(reservation: dict[str, Any]) -> LeaseResponse:
    now = datetime.now(timezone.utc)
    return LeaseResponse(
        id=str(reservation["capacity_reservation_id"]),
        resource_id=str(reservation.get("resource_id") or ""),
        capacity_reservation_id=str(reservation["capacity_reservation_id"]),
        escrow_uid=str(reservation.get("escrow_uid") or ""),
        vm_host=str(reservation.get("vm_host") or ""),
        vm_target=str(reservation.get("vm_target") or ""),
        lease_start_utc=_parse_utc(reservation.get("lease_start_utc")),
        lease_end_utc=_parse_utc(reservation.get("lease_end_utc")) or now,
        status=lease_state_for_reservation_state(str(reservation.get("state"))).value,
        create_job_id=reservation.get("create_job_id"),
        vm_remove_job_id=reservation.get("vm_remove_job_id"),
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
        summary="Register a VM lease on its reservation",
    )
    def create_lease(self, body: LeaseCreate) -> LeaseResponse:
        try:
            attached = self._leases.register_lease(
                ExecutorLeaseRegistration(
                    capacity_reservation_id=body.capacity_reservation_id,
                    escrow_uid=body.escrow_uid,
                    executor_kind=_VM_EXECUTOR_KIND,
                    executor_target=body.vm_target,
                    executor_ref={"vm_host": body.vm_host},
                    lease_start_utc=body.lease_start_utc,
                    lease_end_utc=body.lease_end_utc,
                    create_job_id=body.create_job_id,
                )
            )
        except LeaseNotFoundError as exc:
            raise _http_error(exc) from exc
        logger.info(
            "[LEASES] Attached lease to reservation %s (resource=%s escrow=%s)",
            attached["capacity_reservation_id"], attached.get("resource_id"), body.escrow_uid,
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
            updated = self._leases.update_lease(
                lease_id,
                ExecutorLeaseUpdate(
                    executor_kind=(
                        _VM_EXECUTOR_KIND if body.vm_host or body.vm_target else None
                    ),
                    executor_target=body.vm_target,
                    executor_ref={"vm_host": body.vm_host} if body.vm_host else None,
                    lease_start_utc=body.lease_start_utc,
                    lease_end_utc=body.lease_end_utc,
                    release_job_id=body.vm_remove_job_id,
                    create_job_id=body.create_job_id,
                ),
            )
        except LeaseLifecycleError as exc:
            raise _http_error(exc) from exc
        logger.info("[LEASES] Updated fields on reservation %s", lease_id)
        return _lease_view(updated)

    @router.post(
        "/{lease_id}/terminate",
        response_model=LeaseResponse,
        summary="Terminate a market-managed lease",
        description=(
            "Submits the lease release operation for this provisioning service "
            "based on the reservation's executor_kind and moves the lease to "
            "releasing. Capacity is released only after the delegated release "
            "job succeeds. Failed, cancelled, or timed-out teardown leaves the "
            "lease in release_failed."
        ),
    )
    async def terminate_lease(
        self, lease_id: str, body: LeaseTerminateRequest | None = None,
    ) -> LeaseResponse:
        try:
            reservation = await self._leases.terminate_lease(
                lease_id, body or LeaseTerminateRequest(),
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(reservation)

    @router.post(
        "/{lease_id}/release-oversight",
        response_model=LeaseResponse,
        summary="Release lifecycle oversight without releasing capacity",
        description=(
            "Moves a leased reservation to unmanaged. This does not run the "
            "executor release operation and does not release capacity. An admin "
            "must later clean up the workload/access and force-release capacity."
        ),
    )
    def release_oversight(
        self, lease_id: str, body: LeaseReleaseOversightRequest,
    ) -> LeaseResponse:
        try:
            reservation = self._leases.release_oversight(lease_id, body)
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(reservation)

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
            "executor-dispatched release operation again, returns the lease to "
            "releasing, and keeps capacity held until the retry succeeds."
        ),
    )
    async def retry_release(
        self, lease_id: str, body: LeaseRetryReleaseRequest | None = None,
    ) -> LeaseResponse:
        try:
            reservation = await self._leases.retry_release(
                lease_id, body or LeaseRetryReleaseRequest(),
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(reservation)

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
            reservation = await self._leases.force_release(lease_id, body)
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _http_error(exc) from exc
        return _lease_view(reservation)

    @classmethod
    def make_router(cls) -> APIRouter:
        return admin_router
