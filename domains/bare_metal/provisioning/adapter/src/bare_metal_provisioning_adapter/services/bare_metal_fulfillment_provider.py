"""Provider-neutral fulfillment adapter for accepted bare-metal settlements."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalAccessResult,
    BareMetalLeaseCreate,
    BareMetalMaterialization,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    bare_metal_executor_ref,
    materialization_to_lease_create,
)
from compute_provisioning.contracts import ExecutorActionEnvelope
from market_fulfillment import (
    CredentialFetchFailedError,
    FulfillmentCreateFailedError,
    FulfillmentProvider,
    FulfillmentResult,
    FulfillmentStatusFailedError,
    FulfillmentTeardownFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    ProviderStatus,
    ProvisionedResourceDescriptor,
    SettlementResource,
    SettlementResult,
    VersionedEnvelope,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from bare_metal_provisioning_adapter.services.bare_metal_operations_service import (
    BareMetalOperationsService,
)

_PROVIDER = "bare_metal.ansible"
_CREATE_KIND = "bare_metal.fulfillment.create.v1"
_TEARDOWN_KIND = "bare_metal.fulfillment.teardown.v1"
_RESULT_KIND = "bare_metal.fulfillment.result.v1"

_JOB_STATUS_TO_OPERATION_STATE = {
    "pending": ProviderOperationState.pending,
    "running": ProviderOperationState.pending,
    "succeeded": ProviderOperationState.succeeded,
    "failed": ProviderOperationState.failed,
    "cancelled": ProviderOperationState.failed,
}


class BareMetalPreparedOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity_reservation_id: str = Field(min_length=1)
    action: Literal["create", "teardown"]
    lease: BareMetalLeaseCreate


class BareMetalFulfillmentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    create_job_id: str = Field(min_length=1)
    current_job_id: str = Field(min_length=1)
    teardown_job_id: str | None = None
    operation: Literal["create", "teardown"]
    machine_id: str = Field(min_length=1)
    physical_host_id: str = Field(min_length=1)
    escrow_uid: str | None = Field(default=None, min_length=1)
    settlement_obligation_ref: str | None = Field(default=None, min_length=1)
    lease_start_utc: datetime | None = None
    lease_end_utc: datetime
    access_ref: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_settlement_identity(self) -> "BareMetalFulfillmentMetadata":
        if (
            sum(
                value is not None
                for value in (self.escrow_uid, self.settlement_obligation_ref)
            )
            != 1
        ):
            raise ValueError("fulfillment metadata requires one settlement identity")
        return self


class BareMetalFulfillmentProvider(FulfillmentProvider):
    """Schedule access only for the immutable selected bare-metal resource."""

    provider = _PROVIDER

    def __init__(
        self,
        *,
        operations_service: BareMetalOperationsService,
        job_service: Any,
    ) -> None:
        self._operations = operations_service
        self._job_service = job_service

    @staticmethod
    def _validate_pool_config(pool_config: dict[str, Any]) -> None:
        if pool_config:
            raise ProviderConfigInvalidError(
                "bare-metal provider does not accept pool-local configuration"
            )

    @staticmethod
    def _materialization(request: VersionedEnvelope[Any]) -> BareMetalMaterialization:
        try:
            return BareMetalMaterialization.model_validate(request.payload)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid bare-metal fulfillment requirements: {exc}"
            ) from exc

    @staticmethod
    def _resource_value(resource: SettlementResource, field: str) -> str:
        publication = resource.attributes.get("bare_metal_publication")
        if not isinstance(publication, dict) or publication.get("enabled") is not True:
            raise ProviderConfigInvalidError(
                "selected bare-metal resource has no enabled publication view"
            )
        value = publication.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProviderConfigInvalidError(
                f"selected bare-metal resource requires a non-empty {field} attribute"
            )
        return value

    @classmethod
    def _validate_resource_binding(
        cls,
        *,
        resource: SettlementResource,
        materialization: BareMetalMaterialization,
    ) -> None:
        if resource.executor_kind != BARE_METAL_EXECUTOR_KIND:
            raise ProviderConfigInvalidError(
                "bare-metal provider cannot execute offering mode "
                f"{resource.executor_kind!r}"
            )
        expected_machine = cls._resource_value(resource, "machine_id")
        expected_host = cls._resource_value(resource, "physical_host_id")
        if materialization.machine_id != expected_machine:
            raise ProviderConfigInvalidError(
                "materialization machine_id does not match the selected resource"
            )
        if materialization.physical_host_id != expected_host:
            raise ProviderConfigInvalidError(
                "materialization physical_host_id does not match the selected resource"
            )

    @staticmethod
    def _decode_prepared(
        prepared: VersionedEnvelope[Any],
        *,
        expected_kind: str,
        expected_action: Literal["create", "teardown"],
    ) -> BareMetalPreparedOperation:
        if prepared.kind != expected_kind or prepared.schema_version != 1:
            raise ProviderConfigInvalidError(
                f"unsupported bare-metal {expected_action} envelope"
            )
        try:
            operation = BareMetalPreparedOperation.model_validate(prepared.payload)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid bare-metal {expected_action} envelope: {exc}"
            ) from exc
        if operation.action != expected_action:
            raise ProviderConfigInvalidError(
                f"bare-metal envelope action must be {expected_action!r}"
            )
        if operation.lease.capacity_reservation_id != operation.capacity_reservation_id:
            raise ProviderConfigInvalidError(
                "bare-metal envelope reservation identity is inconsistent"
            )
        return operation

    @staticmethod
    def _metadata(provider_metadata: dict[str, Any]) -> BareMetalFulfillmentMetadata:
        try:
            return BareMetalFulfillmentMetadata.model_validate(provider_metadata)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid bare-metal fulfillment metadata: {exc}"
            ) from exc

    def prepare_create(
        self,
        *,
        capacity_reservation_id: str,
        request: VersionedEnvelope[Any],
        resource: SettlementResource,
        pool_config: dict[str, Any],
    ) -> VersionedEnvelope[Any]:
        self._validate_pool_config(pool_config)
        materialization = self._materialization(request)
        self._validate_resource_binding(
            resource=resource,
            materialization=materialization,
        )
        lease = materialization_to_lease_create(
            materialization,
            capacity_reservation_id=capacity_reservation_id,
        )
        return VersionedEnvelope(
            kind=_CREATE_KIND,
            schema_version=1,
            payload=BareMetalPreparedOperation(
                capacity_reservation_id=capacity_reservation_id,
                action="create",
                lease=lease,
            ).model_dump(mode="json"),
        )

    async def dispatch_create(
        self,
        prepared: VersionedEnvelope[Any],
    ) -> FulfillmentResult:
        try:
            operation = self._decode_prepared(
                prepared,
                expected_kind=_CREATE_KIND,
                expected_action="create",
            )
            lease = operation.lease
            contract = ExecutorActionEnvelope(
                capacity_reservation_id=operation.capacity_reservation_id,
                deal_ref={lease.settlement_identity_kind: lease.settlement_identity},
                executor_kind=BARE_METAL_EXECUTOR_KIND,
                action_kind=NODE_GRANT_ACCESS_ACTION,
                idempotency_key=f"{operation.capacity_reservation_id}:grant-access",
                parameters=lease.model_dump(mode="json", exclude_none=True),
            )
            response = await self._operations.grant_access(lease, contract=contract)
            return FulfillmentResult(
                BareMetalFulfillmentMetadata(
                    create_job_id=response.job_id,
                    current_job_id=response.job_id,
                    operation="create",
                    machine_id=lease.machine_id,
                    physical_host_id=lease.physical_host_id,
                    escrow_uid=lease.escrow_uid,
                    settlement_obligation_ref=lease.settlement_obligation_ref,
                    access_ref=lease.access_ref,
                    lease_start_utc=lease.lease_start_utc,
                    lease_end_utc=lease.lease_end_utc,
                ).model_dump(mode="json", exclude_none=True)
            )
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentCreateFailedError(str(exc)) from exc

    def prepare_teardown(
        self,
        settlement_result: SettlementResult,
        pool_config: dict[str, Any],
    ) -> VersionedEnvelope[Any]:
        self._validate_pool_config(pool_config)
        metadata = self._metadata(settlement_result.provider_metadata)
        resource = settlement_result.resource
        if resource.executor_kind != BARE_METAL_EXECUTOR_KIND:
            raise ProviderConfigInvalidError(
                "bare-metal teardown cannot execute offering mode "
                f"{resource.executor_kind!r}"
            )
        if self._resource_value(resource, "machine_id") != metadata.machine_id:
            raise ProviderConfigInvalidError(
                "fulfillment metadata machine_id does not match the selected resource"
            )
        if (
            self._resource_value(resource, "physical_host_id")
            != metadata.physical_host_id
        ):
            raise ProviderConfigInvalidError(
                "fulfillment metadata physical_host_id does not match the selected resource"
            )
        lease = BareMetalLeaseCreate(
            capacity_reservation_id=settlement_result.capacity_reservation_id,
            escrow_uid=metadata.escrow_uid,
            settlement_obligation_ref=metadata.settlement_obligation_ref,
            machine_id=metadata.machine_id,
            physical_host_id=metadata.physical_host_id,
            lease_start_utc=metadata.lease_start_utc,
            lease_end_utc=metadata.lease_end_utc,
            access_ref=metadata.access_ref,
            create_job_id=metadata.create_job_id,
        )
        return VersionedEnvelope(
            kind=_TEARDOWN_KIND,
            schema_version=1,
            payload=BareMetalPreparedOperation(
                capacity_reservation_id=settlement_result.capacity_reservation_id,
                action="teardown",
                lease=lease,
            ).model_dump(mode="json"),
        )

    async def dispatch_teardown(
        self,
        prepared: VersionedEnvelope[Any],
    ) -> FulfillmentResult:
        try:
            operation = self._decode_prepared(
                prepared,
                expected_kind=_TEARDOWN_KIND,
                expected_action="teardown",
            )
            lease = operation.lease
            contract = ExecutorActionEnvelope(
                capacity_reservation_id=operation.capacity_reservation_id,
                deal_ref={lease.settlement_identity_kind: lease.settlement_identity},
                executor_kind=BARE_METAL_EXECUTOR_KIND,
                action_kind=NODE_RECLAIM_ACCESS_ACTION,
                idempotency_key=f"{operation.capacity_reservation_id}:reclaim-access",
                parameters=lease.model_dump(mode="json", exclude_none=True),
            )
            response = await self._operations.reclaim_access(
                {
                    "capacity_reservation_id": operation.capacity_reservation_id,
                    lease.settlement_identity_kind: lease.settlement_identity,
                    "executor_target": lease.machine_id,
                    "access_ref": lease.access_ref,
                    "executor_ref": bare_metal_executor_ref(
                        lease.physical_host_id,
                        access_ref=lease.access_ref,
                    ),
                },
                contract=contract,
            )
            return FulfillmentResult(
                BareMetalFulfillmentMetadata(
                    create_job_id=lease.create_job_id or response.job_id,
                    teardown_job_id=response.job_id,
                    current_job_id=response.job_id,
                    operation="teardown",
                    machine_id=lease.machine_id,
                    physical_host_id=lease.physical_host_id,
                    escrow_uid=lease.escrow_uid,
                    settlement_obligation_ref=lease.settlement_obligation_ref,
                    access_ref=lease.access_ref,
                    lease_start_utc=lease.lease_start_utc,
                    lease_end_utc=lease.lease_end_utc,
                ).model_dump(mode="json", exclude_none=True)
            )
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentTeardownFailedError(str(exc)) from exc

    def resolve_provisioned_resources(
        self, provider_metadata: dict[str, Any]
    ) -> tuple[str, ...]:
        metadata = self._metadata(provider_metadata)
        return (metadata.physical_host_id,)

    async def get_status(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus:
        del capacity_reservation_id, resource
        try:
            metadata = self._metadata(provider_metadata)
            job = self._job_service.get_job(metadata.current_job_id)
        except ProviderConfigInvalidError as exc:
            return ProviderStatus(ProviderOperationState.unknown, str(exc))
        except LookupError:
            return ProviderStatus(
                ProviderOperationState.unknown,
                f"job {provider_metadata.get('current_job_id')} not found",
            )
        except Exception as exc:
            raise FulfillmentStatusFailedError(str(exc)) from exc
        return ProviderStatus(
            _JOB_STATUS_TO_OPERATION_STATE.get(
                job.status,
                ProviderOperationState.unknown,
            ),
            job.error,
        )

    async def fetch_credentials(
        self,
        provider_metadata: dict[str, Any],
        provisioned_resources: tuple[ProvisionedResourceDescriptor, ...],
    ) -> VersionedEnvelope[Any]:
        del provisioned_resources
        try:
            metadata = self._metadata(provider_metadata)
            job = self._job_service.get_job(metadata.create_job_id)
        except Exception as exc:
            raise CredentialFetchFailedError(str(exc)) from exc

        result = job.result if isinstance(job.result, dict) else {}
        operation_result = result.get("ansible_result")
        if not isinstance(operation_result, dict):
            operation_result = result
        ssh_user = operation_result.get("ssh_user")
        if not isinstance(ssh_user, str) or not ssh_user.strip():
            ssh_user = result.get("tenant_user")
        host = operation_result.get("host")
        if not isinstance(host, str) or not host.strip():
            host = result.get("host")
        port = operation_result.get("port")
        if port is None:
            port = result.get("port", result.get("ssh_port"))
        timestamp = operation_result.get("timestamp")
        if not isinstance(timestamp, str):
            timestamp = result.get("timestamp")
        details = {
            key: result[key]
            for key in ("result_message", "note")
            if isinstance(result.get(key), str) and result[key]
        }
        access_result = BareMetalAccessResult(
            action=NODE_GRANT_ACCESS_ACTION,
            machine_id=metadata.machine_id,
            physical_host_id=metadata.physical_host_id,
            ssh_user=ssh_user if isinstance(ssh_user, str) else None,
            escrow_uid=metadata.escrow_uid,
            settlement_obligation_ref=metadata.settlement_obligation_ref,
            access_grant_ref=metadata.create_job_id,
            host=host if isinstance(host, str) and host.strip() else None,
            port=(
                int(port)
                if not isinstance(port, bool)
                and isinstance(port, (int, str))
                and str(port).isdigit()
                else None
            ),
            lease_expires_at=metadata.lease_end_utc,
            timestamp=timestamp if isinstance(timestamp, str) else None,
            status="success",
            details=details or None,
        )
        return VersionedEnvelope(
            kind=_RESULT_KIND,
            schema_version=1,
            payload=access_result.model_dump(mode="json", exclude_none=True),
        )
