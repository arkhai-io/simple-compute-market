"""Executor-neutral service for the versioned compute provisioning contract."""

from __future__ import annotations

from typing import Any, Protocol

from compute_provisioning import (
    CredentialEnvelope,
    ExecutorActionEnvelope,
    ExecutorAdapterRegistry,
    ExecutorMismatchError,
    JobAccepted,
    LogsReference,
    ProvisioningErrorEnvelope,
    ProvisioningJob,
)
from market_site.authority import SiteAuthorityPort


class ReservationNotProvisionableError(ValueError):
    pass


class ContractJobStore(Protocol):
    def get_contract_job_record(self, job_id: str) -> dict[str, Any]: ...

    def cancel_job(self, job_id: str) -> Any: ...


class ComputeContractService:
    def __init__(
        self,
        *,
        site_authority: SiteAuthorityPort,
        job_service: ContractJobStore,
        adapters: ExecutorAdapterRegistry,
    ) -> None:
        self._site_authority = site_authority
        self._job_service = job_service
        self._adapters = adapters

    async def submit_action(self, envelope: ExecutorActionEnvelope) -> JobAccepted:
        reservation = self._site_authority.get_reservation(envelope.capacity_reservation_id)
        if reservation is None:
            raise ReservationNotProvisionableError(
                f"reservation {envelope.capacity_reservation_id!r} was not found"
            )
        if reservation.get("state") != "leased":
            raise ReservationNotProvisionableError(
                f"reservation {envelope.capacity_reservation_id!r} is "
                f"{reservation.get('state')!r}, not 'leased'"
            )
        expected_executor = str(reservation.get("executor_kind") or "vm")
        if envelope.executor_kind != expected_executor:
            raise ExecutorMismatchError(
                f"reservation executor is {expected_executor!r}, "
                f"not {envelope.executor_kind!r}"
            )
        adapter = self._adapters.get(envelope.executor_kind)
        validated = adapter.validate_parameters(
            envelope.action_kind,
            envelope.parameters,
        )
        job_id = await adapter.submit(envelope, validated)
        record = self._job_service.get_contract_job_record(job_id)
        return JobAccepted.model_validate(record)

    def get_job(self, job_id: str) -> ProvisioningJob:
        record = self._job_service.get_contract_job_record(job_id)
        adapter = self._adapters.get(str(record["executor_kind"]))
        result = (
            adapter.validate_result(str(record["action_kind"]), record["result"])
            if record["result"] is not None
            else None
        )
        credentials = adapter.validate_credentials(
            str(record["action_kind"]),
            record["credentials"],
        )
        error = (
            ProvisioningErrorEnvelope(
                code=(
                    "cancelled"
                    if record["status"] == "cancelled"
                    else "executor_error"
                ),
                message=str(record["error"]),
                retryable=False,
            )
            if record["error"]
            else None
        )
        logs_reference = (
            LogsReference(kind="inline", reference=f"/api/v1/jobs/{job_id}/logs")
            if record["logs"] is not None
            else None
        )
        return ProvisioningJob.model_validate(
            {
                **record,
                "result": result,
                "credentials": credentials,
                "error": error,
                "logs_reference": logs_reference,
            }
        )

    def cancel_job(self, job_id: str) -> ProvisioningJob:
        self._job_service.cancel_job(job_id)
        return self.get_job(job_id)

    def get_credentials(self, job_id: str) -> list[CredentialEnvelope]:
        return self.get_job(job_id).credentials
