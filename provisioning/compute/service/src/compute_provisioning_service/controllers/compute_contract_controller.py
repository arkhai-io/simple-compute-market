"""Versioned executor command, job, and allocation-backed lease routes."""

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
    ProvisioningJob,
    UnsupportedExecutorActionError,
)
from compute_provisioning.executor_leases import ExecutorLeaseRegistration, ExecutorLeaseService
from compute_provisioning.lease_lifecycle import LeaseLifecycleService, LeaseNotFoundError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_utils.cbv import cbv

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.services.compute_contract_service import (
    AllocationNotProvisionableError,
    ComputeContractService,
)

router = APIRouter(tags=["compute-contract"])


def _lease_view(allocation: dict[str, Any]) -> LeaseView:
    def parsed(value: Any) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    executor_ref = dict(allocation.get("executor_ref") or {})
    return LeaseView(
        allocation_id=str(allocation["allocation_id"]),
        deal_ref=dict(allocation.get("deal_ref") or {"escrow_uid": allocation.get("escrow_uid")}),
        executor_kind=str(allocation.get("executor_kind") or "vm"),
        executor_target=str(
            allocation.get("executor_target")
            or allocation.get("vm_target")
            or allocation.get("vm_host")
            or executor_ref.get("physical_host_id")
            or ""
        ),
        lease_start_utc=parsed(allocation.get("lease_start_utc")),
        lease_end_utc=parsed(allocation.get("lease_end_utc")),
        create_job_id=allocation.get("create_job_id"),
        status=str(allocation.get("state")),
        release_job_id=allocation.get("release_job_id"),
        failure_reason=allocation.get("failure_reason"),
        failure_message=allocation.get("failure_message"),
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LeaseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ExecutorMismatchError, AllocationNotProvisionableError)):
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
            allocation = self._executor_leases.register_lease(
                ExecutorLeaseRegistration(
                    allocation_id=body.allocation_id,
                    escrow_uid=str(body.deal_ref.get("escrow_uid") or "") or None,
                    executor_kind=body.executor_kind,
                    executor_target=body.executor_target,
                    lease_start_utc=body.lease_start_utc,
                    lease_end_utc=body.lease_end_utc,
                    create_job_id=body.create_job_id,
                )
            )
            return _lease_view(allocation)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/contract/leases/{allocation_id}", response_model=LeaseView)
    def get_lease(self, allocation_id: str) -> LeaseView:
        try:
            return _lease_view(self._executor_leases.get_lease(allocation_id))
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/contract/leases/{allocation_id}/terminate", response_model=LeaseView)
    async def terminate_lease(self, allocation_id: str, body: LeaseTermination) -> LeaseView:
        try:
            return _lease_view(await self._lease_lifecycle.terminate_lease(allocation_id, body))
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/contract/leases/{allocation_id}/retry-release", response_model=LeaseView)
    async def retry_release(self, allocation_id: str, body: LeaseRetryRelease) -> LeaseView:
        try:
            return _lease_view(await self._lease_lifecycle.retry_release(allocation_id, body))
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/contract/leases/{allocation_id}/force-release", response_model=LeaseView)
    async def force_release(self, allocation_id: str, body: LeaseForceRelease) -> LeaseView:
        try:
            return _lease_view(await self._lease_lifecycle.force_release(allocation_id, body))
        except Exception as exc:
            raise _http_error(exc) from exc

    @classmethod
    def make_router(cls) -> APIRouter:
        return router
