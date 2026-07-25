"""Ansible implementation of the provider-neutral fulfillment contract."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Callable

from compute_provisioning.contracts import ExecutorActionEnvelope
from market_fulfillment import (
    CredentialFetchFailedError,
    ProvisionedResourceDescriptor,
    FulfillmentCreateFailedError,
    FulfillmentProvider,
    FulfillmentResult,
    FulfillmentStatusFailedError,
    FulfillmentTeardownFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    ProviderStatus,
    SettlementResource,
    SettlementResult,
    VersionedEnvelope,
)
from vm_provisioning_adapter.fulfillment_results import (
    VmFulfillmentCredential,
    build_vm_fulfillment_result,
)
from vm_provisioning_adapter.models.fulfillment_model import (
    AnsibleFulfillmentMetadata,
    AnsiblePoolConfig,
    AnsiblePreparedJobParameters,
    AnsiblePreparedOperation,
    VmFulfillmentRequirements,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams

if TYPE_CHECKING:
    from compute_provisioning_service.services.async_job_queue import AsyncJobQueue
    from vm_provisioning_adapter.services.job_service import AnsibleJobService

_CREATE_KIND = "vm.ansible.create.v1"
_TEARDOWN_KIND = "vm.ansible.teardown.v1"
_JOB_STATUS_TO_OPERATION_STATE = {
    "queued": ProviderOperationState.pending,
    "running": ProviderOperationState.pending,
    "succeeded": ProviderOperationState.succeeded,
    "failed": ProviderOperationState.failed,
    "cancelled": ProviderOperationState.failed,
}


class AnsibleFulfillmentProvider(FulfillmentProvider):
    def __init__(
        self,
        *,
        job_service: "AnsibleJobService",
        job_queue_provider: Callable[[], "AsyncJobQueue"],
    ) -> None:
        self._job_service = job_service
        self._job_queue_provider = job_queue_provider

    @staticmethod
    def _pool_config(pool_config: dict[str, Any]) -> AnsiblePoolConfig:
        try:
            return AnsiblePoolConfig.model_validate(pool_config)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid Ansible pool configuration: {exc}"
            ) from exc

    @staticmethod
    def _vm_host(resource: SettlementResource) -> str:
        value = resource.attributes.get("vm_host")
        if not isinstance(value, str) or not value.strip():
            raise ProviderConfigInvalidError(
                "selected VM settlement resource requires a non-empty vm_host attribute"
            )
        return value

    def _validate_extra_vars(
        self,
        params: AnsibleJobParams,
        extra: dict[str, Any],
    ) -> None:
        collisions = sorted(
            self._job_service.reserved_var_keys(params).intersection(extra)
        )
        if collisions:
            raise ProviderConfigInvalidError(
                "provider extra_vars override reserved job variables: "
                + ", ".join(collisions)
            )

    @staticmethod
    def _prepared_parameters(params: AnsibleJobParams) -> AnsiblePreparedJobParameters:
        return AnsiblePreparedJobParameters.model_validate(dataclasses.asdict(params))

    @staticmethod
    def _job_params(parameters: AnsiblePreparedJobParameters) -> AnsibleJobParams:
        return AnsibleJobParams(**parameters.model_dump(mode="python"))

    def prepare_create(
        self,
        *,
        capacity_reservation_id: str,
        request: VersionedEnvelope[Any],
        resource: SettlementResource,
        pool_config: dict[str, Any],
    ) -> VersionedEnvelope[Any]:
        try:
            requirements = VmFulfillmentRequirements.model_validate(request.payload)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid VM fulfillment requirements: {exc}"
            ) from exc

        config = self._pool_config(pool_config)
        params = AnsibleJobParams(
            vm_host=self._vm_host(resource),
            vm_action="create",
            vm_target=requirements.vm_target,
            image_setup_type=requirements.image_setup_type,
            vm_ram=requirements.vm_ram,
            vm_vcpus=requirements.vm_vcpus,
            vm_disk_size=requirements.vm_disk_size,
            vm_os_variant=requirements.vm_os_variant,
            ssh_pubkey=requirements.ssh_pubkey,
            gpu_provisioned=requirements.gpu_provisioned,
            vm_gpu_count=requirements.vm_gpu_count,
            vm_gpu_device=requirements.vm_gpu_device,
            vm_gpu_devices=requirements.vm_gpu_devices,
            vm_gpu_partition_size=requirements.vm_gpu_partition_size,
            escrow_uid=capacity_reservation_id,
            playbook_path=config.playbook_path,
        )
        self._validate_extra_vars(params, config.extra_vars)
        params = dataclasses.replace(params, provider_extra_vars=config.extra_vars)
        operation = AnsiblePreparedOperation(
            capacity_reservation_id=capacity_reservation_id,
            action="create",
            parameters=self._prepared_parameters(params),
        )
        return VersionedEnvelope(
            kind=_CREATE_KIND,
            schema_version=1,
            payload=operation.model_dump(mode="json"),
        )

    async def dispatch_create(
        self,
        prepared: VersionedEnvelope[Any],
    ) -> FulfillmentResult:
        try:
            if prepared.kind != _CREATE_KIND or prepared.schema_version != 1:
                raise ProviderConfigInvalidError(
                    "unsupported Ansible create envelope"
                )
            try:
                operation = AnsiblePreparedOperation.model_validate(prepared.payload)
            except Exception as exc:
                raise ProviderConfigInvalidError(
                    f"invalid Ansible create envelope: {exc}"
                ) from exc
            params = self._job_params(operation.parameters)
            contract = ExecutorActionEnvelope(
                capacity_reservation_id=operation.capacity_reservation_id,
                deal_ref={},
                executor_kind="vm",
                action_kind="create",
                idempotency_key=f"{operation.capacity_reservation_id}:create",
                parameters=operation.parameters.model_dump(mode="json"),
            )
            response = await self._job_service.submit(
                params,
                self._job_queue_provider(),
                contract=contract,
            )
            metadata = AnsibleFulfillmentMetadata(
                create_job_id=response.job_id,
                current_job_id=response.job_id,
                vm_host=params.vm_host,
                vm_target=params.vm_target or "",
                operation="create",
            )
            return FulfillmentResult(metadata.model_dump(mode="json"))
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentCreateFailedError(str(exc)) from exc

    def prepare_teardown(
        self,
        settlement_result: SettlementResult,
        pool_config: dict[str, Any],
    ) -> VersionedEnvelope[Any]:
        try:
            metadata = AnsibleFulfillmentMetadata.model_validate(
                settlement_result.provider_metadata
            )
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid Ansible fulfillment metadata: {exc}"
            ) from exc

        config = self._pool_config(pool_config)
        params = AnsibleJobParams(
            vm_host=metadata.vm_host,
            vm_action="vm_remove",
            vm_target=metadata.vm_target,
            escrow_uid=settlement_result.capacity_reservation_id,
            playbook_path=config.playbook_path,
        )
        self._validate_extra_vars(params, config.extra_vars)
        params = dataclasses.replace(params, provider_extra_vars=config.extra_vars)
        operation = AnsiblePreparedOperation(
            capacity_reservation_id=settlement_result.capacity_reservation_id,
            action="teardown",
            parameters=self._prepared_parameters(params),
        )
        return VersionedEnvelope(
            kind=_TEARDOWN_KIND,
            schema_version=1,
            payload=operation.model_dump(mode="json"),
        )

    async def dispatch_teardown(
        self,
        prepared: VersionedEnvelope[Any],
    ) -> FulfillmentResult:
        try:
            if prepared.kind != _TEARDOWN_KIND or prepared.schema_version != 1:
                raise ProviderConfigInvalidError(
                    "unsupported Ansible teardown envelope"
                )
            try:
                operation = AnsiblePreparedOperation.model_validate(prepared.payload)
            except Exception as exc:
                raise ProviderConfigInvalidError(
                    f"invalid Ansible teardown envelope: {exc}"
                ) from exc
            params = self._job_params(operation.parameters)
            contract = ExecutorActionEnvelope(
                capacity_reservation_id=operation.capacity_reservation_id,
                deal_ref={},
                executor_kind="vm",
                action_kind="teardown",
                idempotency_key=f"{operation.capacity_reservation_id}:teardown",
                parameters=operation.parameters.model_dump(mode="json"),
            )
            response = await self._job_service.submit(
                params,
                self._job_queue_provider(),
                contract=contract,
            )
            metadata = AnsibleFulfillmentMetadata(
                create_job_id="",
                teardown_job_id=response.job_id,
                current_job_id=response.job_id,
                vm_host=params.vm_host,
                vm_target=params.vm_target or "",
                operation="teardown",
            )
            return FulfillmentResult(metadata.model_dump(mode="json"))
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentTeardownFailedError(str(exc)) from exc

    def resolve_provisioned_resources(
        self, provider_metadata: dict[str, Any]
    ) -> tuple[str, ...]:
        try:
            metadata = AnsibleFulfillmentMetadata.model_validate(provider_metadata)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid Ansible fulfillment metadata: {exc}"
            ) from exc
        if not metadata.vm_target.strip():
            raise ProviderConfigInvalidError(
                "Ansible fulfillment metadata requires a non-empty vm_target"
            )
        return (metadata.vm_target,)

    async def get_status(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus:
        try:
            metadata = AnsibleFulfillmentMetadata.model_validate(provider_metadata)
            job_id = metadata.current_job_id
        except Exception as exc:
            return ProviderStatus(
                ProviderOperationState.unknown,
                f"invalid provider metadata: {exc}",
            )

        try:
            job = self._job_service.get_job(job_id)
        except LookupError:
            return ProviderStatus(
                ProviderOperationState.unknown,
                f"job {job_id} not found",
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
        """Fetch live credentials for the job that created this fulfillment's resource.

        Declared async to satisfy the provider-neutral interface, which must
        accommodate providers whose credential store is a real network
        dependency; this adapter's own credential store is the local
        ``AnsibleJobService`` database, so no ``await`` is needed internally
        -- the same shape ``get_status`` already has with ``get_job``.
        """

        try:
            metadata = AnsibleFulfillmentMetadata.model_validate(provider_metadata)
            job_id = metadata.current_job_id
        except Exception as exc:
            raise CredentialFetchFailedError(
                f"invalid provider metadata: {exc}"
            ) from exc

        try:
            response = self._job_service.get_credentials(job_id)
        except LookupError as exc:
            raise CredentialFetchFailedError(f"job {job_id} not found") from exc
        except Exception as exc:
            raise CredentialFetchFailedError(str(exc)) from exc

        output_ids = tuple(
            resource.provisioned_resource_id for resource in provisioned_resources
        )
        return build_vm_fulfillment_result(
            provisioned_resources,
            tuple(
                VmFulfillmentCredential(
                    role=credential.role,
                    password=credential.password,
                    ssh_commands=credential.ssh_commands,
                    provisioned_resource_ids=output_ids,
                )
                for credential in response.credentials
            ),
        )
