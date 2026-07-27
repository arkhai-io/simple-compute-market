"""Versioned executor command, job, and reservation-backed lease routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from compute_provisioning import (
    ExecutorActionEnvelope,
    ExecutorMismatchError,
    JobAccepted,
    LeaseForceRelease,
    LeaseRegistration,
    LeaseRetryRelease,
    LeaseTermination,
    LeaseView,
    lease_state_for_reservation_state,
    ProvisioningJob,
    UnsupportedExecutorActionError,
)
from compute_provisioning.executor_leases import ExecutorLeaseRegistration, ExecutorLeaseService
from compute_provisioning.lease_lifecycle import LeaseLifecycleService, LeaseNotFoundError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_utils.cbv import cbv

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.compute_contract_service import (
    ReservationNotProvisionableError,
    ComputeContractService,
)

router = APIRouter(tags=["compute-contract"])

# Translates market_site's raw ReservationState vocabulary (reserved,
# provisioning, leased, ...) into this contract's LeaseState vocabulary.
# Mirrors vm_provisioning_adapter.controllers.leases_controller._LEASE_STATUS
# -- kept as a second copy rather than a shared import because the two
# controllers sit in different packages and this mapping is small and
# stable; if it drifts, the regression test in
# tests/integration/test_compute_contract_api.py catches it.
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


def _lease_view(reservation: dict[str, Any]) -> LeaseView:
    def parsed(value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    raw_state = str(reservation.get("state"))
    executor_ref = dict(reservation.get("executor_ref") or {})
    return LeaseView(
        capacity_reservation_id=str(reservation["capacity_reservation_id"]),
        deal_ref=dict(reservation.get("deal_ref") or {"escrow_uid": reservation.get("escrow_uid")}),
        executor_kind=str(reservation.get("executor_kind") or "vm"),
        executor_target=str(
            reservation.get("executor_target")
            or reservation.get("vm_target")
            or reservation.get("vm_host")
            or executor_ref.get("physical_host_id")
            or ""
        ),
        lease_start_utc=parsed(reservation.get("lease_start_utc")),
        lease_end_utc=parsed(reservation.get("lease_end_utc")),
        create_job_id=reservation.get("create_job_id"),
        status=_LEASE_STATUS.get(raw_state, raw_state),
        release_job_id=reservation.get("release_job_id"),
        failure_reason=reservation.get("failure_reason"),
        failure_message=reservation.get("failure_message"),
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LeaseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ExecutorMismatchError, ReservationNotProvisionableError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, UnsupportedExecutorActionError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@cbv(router)
class ComputeContractController:
    def __init__(
        self,
        contract_service: ComputeContractService = Depends(
            lambda: _container_module.resolved_compute_contract_service
        ),
        executor_leases: ExecutorLeaseService = Depends(
            lambda: _container_module.resolved_executor_lease_service
        ),
        lease_lifecycle: LeaseLifecycleService = Depends(
            lambda: _container_module.resolved_lease_lifecycle_service
        ),
    ) -> None:
        self._contract = contract_service
        self._executor_leases = executor_leases
        self._lease_lifecycle = lease_lifecycle

    @router.post("/actions", response_model=JobAccepted, status_code=status.HTTP_202_ACCEPTED)
    async def submit_action(self, body: ExecutorActionEnvelope) -> JobAccepted:
        try:
            return await self._contract.submit_action(body)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/jobs/{job_id}/contract", response_model=ProvisioningJob)
    def get_job(self, job_id: str) -> ProvisioningJob:
        try:
            return self._contract.get_job(job_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/jobs/{job_id}/contract/credentials")
    def get_credentials(self, job_id: str) -> dict[str, Any]:
        try:
            return {"credentials": self._contract.get_credentials(job_id)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/jobs/{job_id}/contract/cancel", response_model=ProvisioningJob)
    def cancel_job(self, job_id: str) -> ProvisioningJob:
        try:
            return self._contract.cancel_job(job_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/contract/leases", response_model=LeaseView)
    def register_lease(self, body: LeaseRegistration) -> LeaseView:
        try:
            reservation = self._executor_leases.register_lease(
                ExecutorLeaseRegistration(
                    capacity_reservation_id=body.capacity_reservation_id,
                    escrow_uid=str(body.deal_ref.get("escrow_uid") or "") or None,
                    executor_kind=body.executor_kind,
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
