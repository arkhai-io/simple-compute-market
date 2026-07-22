"""Bare-metal lease adapter for the transitional multi-domain provisioner."""

from __future__ import annotations

import logging
from typing import Any

from arkhai_bare_metal import (
    PHYSICAL_HOST_ID_REF_KEY,
    BareMetalLeaseCreate,
    BareMetalLeaseView,
)
from fastapi import APIRouter, Depends, HTTPException
from fastapi_utils.cbv import cbv

from compute_provisioning_service import container as _container_module
from bare_metal_provisioning_adapter.services.bare_metal_lease_service import (
    BareMetalLeaseService,
    bare_metal_access_ref,
)
from bare_metal_provisioning_adapter.services.bare_metal_operations_service import (
    BareMetalHostValidationError,
    BareMetalOperationsService,
)
from compute_provisioning.lease_lifecycle import LeaseNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bare-metal/leases", tags=["bare-metal"])


def _physical_host_id(reservation: dict[str, Any]) -> str:
    executor_ref = reservation.get("executor_ref")
    if isinstance(executor_ref, dict):
        value = executor_ref.get(PHYSICAL_HOST_ID_REF_KEY)
        if value:
            return str(value)
    return ""


def _lease_view(reservation: dict[str, Any]) -> BareMetalLeaseView:
    return BareMetalLeaseView(
        capacity_reservation_id=str(reservation["capacity_reservation_id"]),
        escrow_uid=reservation.get("escrow_uid"),
        machine_id=str(reservation.get("executor_target") or ""),
        physical_host_id=_physical_host_id(reservation),
        lease_start_utc=reservation.get("lease_start_utc"),
        lease_end_utc=reservation.get("lease_end_utc"),
        state=str(reservation.get("state")),
        release_job_id=reservation.get("release_job_id")
        or reservation.get("vm_remove_job_id"),
        access_ref=bare_metal_access_ref(reservation),
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LeaseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, BareMetalHostValidationError):
        return HTTPException(status_code=exc.status_code, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@cbv(router)
class BareMetalLeasesController:
    def __init__(
        self,
        bare_metal_lease_service: BareMetalLeaseService = Depends(
            lambda: _container_module.resolved_bare_metal_lease_service
        ),
        bare_metal_operations_service: BareMetalOperationsService = Depends(
            lambda: _container_module.resolved_bare_metal_operations_service
        ),
    ) -> None:
        self._leases = bare_metal_lease_service
        self._operations = bare_metal_operations_service

    @router.get(
        "/",
        response_model=list[BareMetalLeaseView],
        summary="List bare-metal leases",
    )
    def list_leases(self) -> list[BareMetalLeaseView]:
        return [_lease_view(reservation) for reservation in self._leases.list_leases()]

    @router.post(
        "/",
        response_model=BareMetalLeaseView,
        status_code=201,
        summary="Register a bare-metal lease on its reservation",
    )
    async def create_lease(self, body: BareMetalLeaseCreate) -> BareMetalLeaseView:
        try:
            if not body.create_job_id:
                grant = await self._operations.grant_access(body)
                body = body.model_copy(update={"create_job_id": grant.job_id})
            attached = self._leases.register_lease(body)
        except (LeaseNotFoundError, BareMetalHostValidationError) as exc:
            raise _http_error(exc) from exc
        logger.info(
            "[BARE_METAL_LEASES] Attached lease to reservation %s (machine=%s escrow=%s)",
            attached["capacity_reservation_id"],
            body.machine_id,
            body.escrow_uid,
        )
        return _lease_view(attached)

    @router.get(
        "/by-escrow/{escrow_uid}",
        response_model=BareMetalLeaseView,
        summary="Get bare-metal lease by escrow UID",
    )
    def get_lease_by_escrow(self, escrow_uid: str) -> BareMetalLeaseView:
        try:
            return _lease_view(self._leases.get_lease_by_escrow(escrow_uid))
        except LeaseNotFoundError as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/{lease_id}",
        response_model=BareMetalLeaseView,
        summary="Get bare-metal lease by reservation ID",
    )
    def get_lease(self, lease_id: str) -> BareMetalLeaseView:
        try:
            return _lease_view(self._leases.get_lease(lease_id))
        except LeaseNotFoundError as exc:
            raise _http_error(exc) from exc

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
