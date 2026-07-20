"""In-place service adapter for the versioned compute provisioning contract."""

from __future__ import annotations

from typing import Any, Mapping

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    NODE_GRANT_ACCESS_ACTION,
    BareMetalLeaseCreate,
)
from compute_provisioning import (
    COMPUTE_PROVISIONING_CONTRACT_VERSION,
    CredentialEnvelope,
    ExecutorActionEnvelope,
    ExecutorAdapterRegistry,
    ExecutorMismatchError,
    JobAccepted,
    LogsReference,
    ProvisioningErrorEnvelope,
    ProvisioningJob,
    ResultEnvelope,
    UnsupportedExecutorActionError,
)
from market_site.authority import SiteAuthorityPort
from vm_provisioning_operator.models import CreateVmRequest
from compute_provisioning_service.services.bare_metal_operations_service import BareMetalOperationsService
from vm_provisioning_adapter.services.job_service import AnsibleJobService
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService


class AllocationNotProvisionableError(ValueError):
    pass


class VmComputeAdapter:
    executor_kind = "vm"

    def __init__(self, site_authority: SiteAuthorityPort, operations: VmOperationsService) -> None:
        self._site_authority = site_authority
        self._operations = operations

    def validate_parameters(self, action_kind: str, parameters: Mapping[str, Any]) -> CreateVmRequest:
        if action_kind != "create":
            raise UnsupportedExecutorActionError(f"VM action {action_kind!r} is not supported")
        return CreateVmRequest.model_validate(parameters)

    async def submit(self, envelope: ExecutorActionEnvelope, validated_parameters: CreateVmRequest) -> str:
        allocation = self._site_authority.get_allocation(envelope.allocation_id) or {}
        host = str(allocation.get("executor_target") or allocation.get("vm_host") or "")
        if not host:
            raise AllocationNotProvisionableError("VM allocation has no executor target")
        accepted = await self._operations.create_vm(
            host=host, body=validated_parameters, contract=envelope
        )
        return accepted.job_id

    def validate_result(self, action_kind: str, result: Mapping[str, Any]) -> ResultEnvelope:
        return ResultEnvelope(executor_kind=self.executor_kind, result_kind=f"vm_{action_kind}", value=dict(result))

    def validate_credentials(self, action_kind: str, credentials: list[Mapping[str, Any]]) -> list[CredentialEnvelope]:
        return [
            CredentialEnvelope(
                executor_kind=self.executor_kind,
                credential_kind=str(item.get("role") or "access"),
                value={key: value for key, value in item.items() if key != "role" and value is not None},
            )
            for item in credentials
        ]


class BareMetalComputeAdapter:
    executor_kind = BARE_METAL_EXECUTOR_KIND

    def __init__(self, site_authority: SiteAuthorityPort, operations: BareMetalOperationsService) -> None:
        self._site_authority = site_authority
        self._operations = operations

    def validate_parameters(self, action_kind: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        if action_kind != NODE_GRANT_ACCESS_ACTION:
            raise UnsupportedExecutorActionError(f"bare-metal action {action_kind!r} is not supported")
        return dict(parameters)

    async def submit(self, envelope: ExecutorActionEnvelope, validated_parameters: dict[str, Any]) -> str:
        allocation = self._site_authority.get_allocation(envelope.allocation_id) or {}
        deal_ref = dict(envelope.deal_ref)
        executor_ref = dict(allocation.get("executor_ref") or {})
        body = BareMetalLeaseCreate.model_validate({
            **validated_parameters,
            "allocation_id": envelope.allocation_id,
            "escrow_uid": deal_ref.get("escrow_uid") or allocation.get("escrow_uid"),
            "machine_id": allocation.get("executor_target"),
            "physical_host_id": executor_ref.get("physical_host_id"),
            "lease_start_utc": allocation.get("lease_start_utc"),
            "lease_end_utc": allocation.get("lease_end_utc"),
            "access_ref": executor_ref.get("access_ref") or validated_parameters.get("access_ref"),
        })
        accepted = await self._operations.grant_access(body, contract=envelope)
        return accepted.job_id

    def validate_result(self, action_kind: str, result: Mapping[str, Any]) -> ResultEnvelope:
        return ResultEnvelope(executor_kind=self.executor_kind, result_kind="bare_metal_access", value=dict(result))

    def validate_credentials(self, action_kind: str, credentials: list[Mapping[str, Any]]) -> list[CredentialEnvelope]:
        return [
            CredentialEnvelope(
                executor_kind=self.executor_kind,
                credential_kind=str(item.get("role") or "access"),
                value={key: value for key, value in item.items() if key != "role" and value is not None},
            )
            for item in credentials
        ]


class ComputeContractService:
    def __init__(
        self,
        *,
        site_authority: SiteAuthorityPort,
        job_service: AnsibleJobService,
        adapters: ExecutorAdapterRegistry,
    ) -> None:
        self._site_authority = site_authority
        self._job_service = job_service
        self._adapters = adapters

    async def submit_action(self, envelope: ExecutorActionEnvelope) -> JobAccepted:
        allocation = self._site_authority.get_allocation(envelope.allocation_id)
        if allocation is None:
            raise AllocationNotProvisionableError(
                f"allocation {envelope.allocation_id!r} was not found"
            )
        if allocation.get("state") != "leased":
            raise AllocationNotProvisionableError(
                f"allocation {envelope.allocation_id!r} is {allocation.get('state')!r}, not 'leased'"
            )
        expected_executor = str(allocation.get("executor_kind") or "vm")
        if envelope.executor_kind != expected_executor:
            raise ExecutorMismatchError(
                f"allocation executor is {expected_executor!r}, not {envelope.executor_kind!r}"
            )
        adapter = self._adapters.get(envelope.executor_kind)
        validated = adapter.validate_parameters(envelope.action_kind, envelope.parameters)
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
            str(record["action_kind"]), record["credentials"]
        )
        error = (
            ProvisioningErrorEnvelope(
                code="cancelled" if record["status"] == "cancelled" else "executor_error",
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
        return ProvisioningJob.model_validate({
            **record,
            "result": result,
            "credentials": credentials,
            "error": error,
            "logs_reference": logs_reference,
        })

    def cancel_job(self, job_id: str) -> ProvisioningJob:
        self._job_service.cancel_job(job_id)
        return self.get_job(job_id)

    def get_credentials(self, job_id: str) -> list[CredentialEnvelope]:
        return self.get_job(job_id).credentials


def build_compute_contract_service(
    *,
    site_authority: SiteAuthorityPort,
    job_service: AnsibleJobService,
    vm_operations: VmOperationsService,
    bare_metal_operations: BareMetalOperationsService,
) -> ComputeContractService:
    return ComputeContractService(
        site_authority=site_authority,
        job_service=job_service,
        adapters=ExecutorAdapterRegistry([
            VmComputeAdapter(site_authority, vm_operations),
            BareMetalComputeAdapter(site_authority, bare_metal_operations),
        ]),
    )
