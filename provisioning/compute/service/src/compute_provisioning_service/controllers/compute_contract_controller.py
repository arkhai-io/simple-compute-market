"""Reservation-backed lease routes of the versioned compute provisioning contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from compute_provisioning_contracts import (
    LeaseForceRelease,
    LeaseRegistration,
    LeaseRetryRelease,
    LeaseTermination,
    LeaseView,
    lease_state_for_reservation_state,
)
from compute_provisioning.executor_leases import ExecutorLeaseRegistration, ExecutorLeaseService
from compute_provisioning.lease_lifecycle import LeaseLifecycleService, LeaseNotFoundError
from fastapi import APIRouter, Depends, HTTPException
from fastapi_utils.cbv import cbv

from compute_provisioning_service import container as _container_module

router = APIRouter(tags=["compute-contract"])


class _ReservationModeMissingError(ValueError):
    """A reservation records no offering mode, so no lease view can be built.

    Every reservation records the mode its claim named; one without it is
    corrupt data, answered as a conflict rather than a client error.
    """


def _lease_view(reservation: dict[str, Any]) -> LeaseView:
    def parsed(value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    raw_state = str(reservation.get("state"))
    executor_ref = dict(reservation.get("executor_ref") or {})
    offering_mode = reservation.get("offering_mode")
    if not offering_mode:
        raise _ReservationModeMissingError(
            "reservation records no explicit offering mode"
        )
    return LeaseView(
        capacity_reservation_id=str(reservation["capacity_reservation_id"]),
        deal_ref=dict(reservation.get("deal_ref") or {"escrow_uid": reservation.get("escrow_uid")}),
        offering_mode=str(offering_mode),
        executor_target=str(
            reservation.get("executor_target")
            or reservation.get("vm_target")
            or reservation.get("host_id")
            or executor_ref.get("physical_host_id")
            or ""
        ),
        lease_start_utc=parsed(reservation.get("lease_start_utc")),
        lease_end_utc=parsed(reservation.get("lease_end_utc")),
        create_job_id=reservation.get("create_job_id"),
        status=lease_state_for_reservation_state(raw_state).value,
        release_job_id=reservation.get("release_job_id"),
        failure_reason=reservation.get("failure_reason"),
        failure_message=reservation.get("failure_message"),
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LeaseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, _ReservationModeMissingError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@cbv(router)
class ComputeContractController:
    def __init__(
        self,
        executor_leases: ExecutorLeaseService = Depends(
            lambda: _container_module.resolved_executor_lease_service
        ),
        lease_lifecycle: LeaseLifecycleService = Depends(
            lambda: _container_module.resolved_lease_lifecycle_service
        ),
    ) -> None:
        self._executor_leases = executor_leases
        self._lease_lifecycle = lease_lifecycle

    @router.post("/contract/leases", response_model=LeaseView)
    def register_lease(self, body: LeaseRegistration) -> LeaseView:
        try:
            reservation = self._executor_leases.register_lease(
                ExecutorLeaseRegistration(
                    capacity_reservation_id=body.capacity_reservation_id,
                    escrow_uid=str(body.deal_ref.get("escrow_uid") or "") or None,
                    offering_mode=body.offering_mode,
                    executor_target=body.executor_target,
                    lease_start_utc=body.lease_start_utc,
                    lease_end_utc=body.lease_end_utc,
                    create_job_id=body.create_job_id,
                )
            )
            return _lease_view(reservation)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/contract/leases/{capacity_reservation_id}", response_model=LeaseView)
    def get_lease(self, capacity_reservation_id: str) -> LeaseView:
        try:
            return _lease_view(self._executor_leases.get_lease(capacity_reservation_id))
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/contract/leases/{capacity_reservation_id}/terminate", response_model=LeaseView)
    async def terminate_lease(self, capacity_reservation_id: str, body: LeaseTermination) -> LeaseView:
        try:
            return _lease_view(await self._lease_lifecycle.terminate_lease(capacity_reservation_id, body))
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/contract/leases/{capacity_reservation_id}/retry-release", response_model=LeaseView)
    async def retry_release(self, capacity_reservation_id: str, body: LeaseRetryRelease) -> LeaseView:
        try:
            return _lease_view(await self._lease_lifecycle.retry_release(capacity_reservation_id, body))
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/contract/leases/{capacity_reservation_id}/force-release", response_model=LeaseView)
    async def force_release(self, capacity_reservation_id: str, body: LeaseForceRelease) -> LeaseView:
        try:
            return _lease_view(await self._lease_lifecycle.force_release(capacity_reservation_id, body))
        except Exception as exc:
            raise _http_error(exc) from exc

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
