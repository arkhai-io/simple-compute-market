"""HTTP clients for the versioned compute provisioning contract."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx

from .contracts import (
    CredentialEnvelope,
    ExecutorActionEnvelope,
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
    FulfillmentValidationResponse,
    JobAccepted,
    LeaseForceRelease,
    LeaseRegistration,
    LeaseRetryRelease,
    LeaseTermination,
    LeaseView,
    ProvisioningJob,
)
from market_fulfillment import VersionedEnvelope


class ComputeProvisioningError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ComputeProvisioningJobError(ComputeProvisioningError):
    pass


class ComputeProvisioningTimeoutError(ComputeProvisioningError):
    pass


class ComputeProvisioningClientProtocol(Protocol):
    async def submit_action(self, envelope: ExecutorActionEnvelope) -> JobAccepted: ...
    async def get_job(self, job_id: str) -> ProvisioningJob: ...
    async def cancel_job(self, job_id: str) -> ProvisioningJob: ...
    async def get_job_credentials(self, job_id: str) -> list[CredentialEnvelope]: ...
    async def register_lease(self, registration: LeaseRegistration) -> LeaseView: ...
    async def get_lease(self, capacity_reservation_id: str) -> LeaseView: ...
    async def terminate_lease(self, capacity_reservation_id: str, request: LeaseTermination) -> LeaseView: ...
    async def retry_lease_release(self, capacity_reservation_id: str, request: LeaseRetryRelease) -> LeaseView: ...
    async def force_release_lease(self, capacity_reservation_id: str, request: LeaseForceRelease) -> LeaseView: ...
    async def schedule_resource(self, request: FulfillmentScheduleRequest) -> FulfillmentScheduleResponse: ...
    async def begin_fulfillment(self, body: FulfillmentRequestBody) -> FulfillmentAcceptanceResponse: ...
    async def begin_fulfillment_teardown(self, fulfillment_id: str) -> FulfillmentAcceptanceResponse: ...
    async def get_fulfillment_status(self, fulfillment_id: str) -> FulfillmentStatusResponse: ...
    async def get_fulfillment_result(self, fulfillment_id: str) -> VersionedEnvelope[dict[str, Any]]: ...
    async def run_fulfillment_convergence_cycle(self) -> dict[str, Any]: ...


class ComputeProvisioningClient:
    def __init__(
        self,
        base_url: str,
        admin_key: str | None = None,
        agent_id: str | None = None,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers: dict[str, str] = {}
        if admin_key:
            headers["X-Admin-Key"] = admin_key
        if agent_id:
            headers["X-Agent-ID"] = agent_id
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport, headers=headers
        )

    async def __aenter__(self) -> "ComputeProvisioningClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise ComputeProvisioningError(str(detail), status_code=response.status_code)

    async def _request(self, method: str, path: str, body: Any | None = None) -> Any:
        payload = body.model_dump(mode="json", exclude_none=True) if hasattr(body, "model_dump") else body
        response = await self._client.request(method, path, json=payload)
        self._raise(response)
        return response.json()

    async def submit_action(self, envelope: ExecutorActionEnvelope) -> JobAccepted:
        return JobAccepted.model_validate(await self._request("POST", "/api/v1/actions", envelope))

    async def get_job(self, job_id: str) -> ProvisioningJob:
        return ProvisioningJob.model_validate(await self._request("GET", f"/api/v1/jobs/{job_id}/contract"))

    async def cancel_job(self, job_id: str) -> ProvisioningJob:
        return ProvisioningJob.model_validate(await self._request("POST", f"/api/v1/jobs/{job_id}/contract/cancel", {}))

    async def get_job_credentials(self, job_id: str) -> list[CredentialEnvelope]:
        payload = await self._request("GET", f"/api/v1/jobs/{job_id}/contract/credentials")
        return [CredentialEnvelope.model_validate(item) for item in payload.get("credentials", [])]

    async def poll_until_complete(
        self, job_id: str, *, timeout: float = 600.0, poll_interval: float = 2.0
    ) -> ProvisioningJob:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            job = await self.get_job(job_id)
            if job.status.value == "succeeded":
                return job
            if job.status.value in {"failed", "cancelled"}:
                message = job.error.message if job.error else f"job {job_id} {job.status.value}"
                raise ComputeProvisioningJobError(message)
            if loop.time() >= deadline:
                raise ComputeProvisioningTimeoutError(f"job {job_id} did not finish within {timeout}s")
            await asyncio.sleep(poll_interval)

    async def register_lease(self, registration: LeaseRegistration) -> LeaseView:
        return LeaseView.model_validate(await self._request("POST", "/api/v1/contract/leases", registration))

    async def get_lease(self, capacity_reservation_id: str) -> LeaseView:
        return LeaseView.model_validate(await self._request("GET", f"/api/v1/contract/leases/{capacity_reservation_id}"))

    async def terminate_lease(self, capacity_reservation_id: str, request: LeaseTermination) -> LeaseView:
        return LeaseView.model_validate(await self._request("POST", f"/api/v1/contract/leases/{capacity_reservation_id}/terminate", request))

    async def retry_lease_release(self, capacity_reservation_id: str, request: LeaseRetryRelease) -> LeaseView:
        return LeaseView.model_validate(await self._request("POST", f"/api/v1/contract/leases/{capacity_reservation_id}/retry-release", request))

    async def force_release_lease(self, capacity_reservation_id: str, request: LeaseForceRelease) -> LeaseView:
        return LeaseView.model_validate(await self._request("POST", f"/api/v1/contract/leases/{capacity_reservation_id}/force-release", request))

    async def run_fulfillment_convergence_cycle(self) -> dict[str, Any]:
        """Run one production fulfillment convergence cycle."""
        return await self._request(
            "POST", "/api/v1/system/fulfillment-convergence/run-cycle", {}
        )

    async def schedule_resource(self, request: FulfillmentScheduleRequest) -> FulfillmentScheduleResponse:
        return FulfillmentScheduleResponse.model_validate(
            await self._request("POST", "/api/v1/fulfillment/schedule", request)
        )

    async def begin_fulfillment(self, body: FulfillmentRequestBody) -> FulfillmentAcceptanceResponse:
        return FulfillmentAcceptanceResponse.model_validate(
            await self._request("POST", "/api/v1/fulfillment/begin", body)
        )

    async def begin_fulfillment_teardown(self, fulfillment_id: str) -> FulfillmentAcceptanceResponse:
        return FulfillmentAcceptanceResponse.model_validate(
            await self._request("POST", f"/api/v1/fulfillment/{fulfillment_id}/begin-teardown", {})
        )

    async def get_fulfillment_status(self, fulfillment_id: str) -> FulfillmentStatusResponse:
        return FulfillmentStatusResponse.model_validate(
            await self._request("GET", f"/api/v1/fulfillment/{fulfillment_id}/status")
        )

    async def get_fulfillment_result(self, fulfillment_id: str) -> VersionedEnvelope[dict[str, Any]]:
        return VersionedEnvelope[dict[str, Any]].model_validate(
            await self._request("GET", f"/api/v1/fulfillment/{fulfillment_id}/result")
        )
