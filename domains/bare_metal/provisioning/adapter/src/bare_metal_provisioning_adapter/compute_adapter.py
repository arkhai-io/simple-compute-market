"""Bare-metal implementation of the opaque compute executor contract."""

from __future__ import annotations

from typing import Any, Mapping

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    NODE_GRANT_ACCESS_ACTION,
    BareMetalLeaseCreate,
)
from compute_provisioning import (
    CredentialEnvelope,
    ExecutorActionEnvelope,
    ResultEnvelope,
    UnsupportedExecutorActionError,
)
from market_site.authority import SiteAuthorityPort

from compute_provisioning_service.services.compute_contract_service import (
    AllocationNotProvisionableError,
)
from bare_metal_provisioning_adapter.services.bare_metal_operations_service import (
    BareMetalOperationsService,
)


class BareMetalComputeAdapter:
    executor_kind = BARE_METAL_EXECUTOR_KIND

    def __init__(
        self,
        site_authority: SiteAuthorityPort,
        operations: BareMetalOperationsService,
    ) -> None:
        self._site_authority = site_authority
        self._operations = operations

    def validate_parameters(
        self, action_kind: str, parameters: Mapping[str, Any]
    ) -> dict[str, Any]:
        if action_kind != NODE_GRANT_ACCESS_ACTION:
            raise UnsupportedExecutorActionError(
                f"bare-metal action {action_kind!r} is not supported"
            )
        return dict(parameters)

    async def submit(
        self,
        envelope: ExecutorActionEnvelope,
        validated_parameters: dict[str, Any],
    ) -> str:
        allocation = self._site_authority.get_allocation(envelope.allocation_id) or {}
        deal_ref = dict(envelope.deal_ref)
        executor_ref = dict(allocation.get("executor_ref") or {})
        body = BareMetalLeaseCreate.model_validate(
            {
                **validated_parameters,
                "allocation_id": envelope.allocation_id,
                "escrow_uid": deal_ref.get("escrow_uid")
                or allocation.get("escrow_uid"),
                "machine_id": allocation.get("executor_target"),
                "physical_host_id": executor_ref.get("physical_host_id"),
                "lease_start_utc": allocation.get("lease_start_utc"),
                "lease_end_utc": allocation.get("lease_end_utc"),
                "access_ref": executor_ref.get("access_ref")
                or validated_parameters.get("access_ref"),
            }
        )
        accepted = await self._operations.grant_access(body, contract=envelope)
        return accepted.job_id

    def validate_result(
        self, action_kind: str, result: Mapping[str, Any]
    ) -> ResultEnvelope:
        return ResultEnvelope(
            executor_kind=self.executor_kind,
            result_kind="bare_metal_access",
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
