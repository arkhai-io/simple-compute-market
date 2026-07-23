"""VM implementation of the opaque compute executor contract."""

from __future__ import annotations

from typing import Any, Mapping

from compute_provisioning import (
    CredentialEnvelope,
    ExecutorActionEnvelope,
    ResultEnvelope,
    UnsupportedExecutorActionError,
)
from market_site.authority import SiteAuthorityPort
from vm_provisioning_operator.models import CreateVmRequest

from compute_provisioning_service.services.compute_contract_service import (
    ReservationNotProvisionableError,
)
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService

VM_EXECUTOR_KIND = "vm"


class VmComputeAdapter:
    executor_kind = VM_EXECUTOR_KIND

    def __init__(
        self,
        site_authority: SiteAuthorityPort,
        operations: VmOperationsService,
    ) -> None:
        self._site_authority = site_authority
        self._operations = operations

    def validate_parameters(
        self, action_kind: str, parameters: Mapping[str, Any]
    ) -> CreateVmRequest:
        if action_kind != "create":
            raise UnsupportedExecutorActionError(
                f"VM action {action_kind!r} is not supported"
            )
        return CreateVmRequest.model_validate(parameters)

    async def submit(
        self,
        envelope: ExecutorActionEnvelope,
        validated_parameters: CreateVmRequest,
    ) -> str:
        reservation = self._site_authority.get_reservation(envelope.capacity_reservation_id) or {}
        host = str(
            reservation.get("executor_target") or reservation.get("vm_host") or ""
        )
        if not host:
            raise ReservationNotProvisionableError(
                "VM reservation has no executor target"
            )
        accepted = await self._operations.create_vm(
            host=host,
            body=validated_parameters,
            contract=envelope,
        )
        return accepted.job_id

    def validate_result(
        self, action_kind: str, result: Mapping[str, Any]
    ) -> ResultEnvelope:
        return ResultEnvelope(
            executor_kind=self.executor_kind,
            result_kind=f"vm_{action_kind}",
            value=dict(result),
        )

    def validate_credentials(
        self,
        action_kind: str,
        credentials: list[Mapping[str, Any]],
    ) -> list[CredentialEnvelope]:
        return [
            CredentialEnvelope(
                executor_kind=self.executor_kind,
                credential_kind=str(item.get("role") or "access"),
                value={
                    key: value
                    for key, value in item.items()
                    if key != "role" and value is not None
                },
            )
            for item in credentials
        ]
