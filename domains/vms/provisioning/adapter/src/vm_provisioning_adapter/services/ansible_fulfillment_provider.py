"""Ansible implementation of FulfillmentProvider."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from compute_provisioning import ExecutorActionEnvelope
from market_fulfillment import (
    PhysicalSettlementRequest,
    SettlementResource,
    VersionedEnvelope,
)
from vm_provisioning_adapter.models.jobs_model import AnsibleJobParams
from vm_provisioning_adapter.models.fulfillment_model import AnsibleFulfillmentMetadata, VmFulfillmentRequirements
from market_fulfillment import (
    FulfillmentCreateFailedError,
    FulfillmentProvider,
    FulfillmentResult,
    FulfillmentStatusFailedError,
    LiveCredential,
    LiveCredentialResult,
    FulfillmentTeardownFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    ProviderStatus,
)

if TYPE_CHECKING:
    from market_resource_pools import ResourcePoolService
    from compute_provisioning_service.services.async_job_queue import AsyncJobQueue
    from vm_provisioning_adapter.services.job_service import AnsibleJobService


@dataclass(frozen=True)
class AnsiblePoolConfig:
    """Provider-local, typed view of a pool's Ansible provider configuration.

    Deliberately narrower than persisted provider configuration:
    ``inventory_group`` is not used for dispatch because concrete placement
    belongs exclusively to ``PhysicalSettlementScheduler``. Treating an
    inventory group as placement would introduce a conflicting scheduler.
    """

    playbook_path: str
    extra_vars: dict[str, Any]


_JOB_STATUS_TO_OPERATION_STATE = {
    "queued": ProviderOperationState.pending,
    "running": ProviderOperationState.pending,
    "succeeded": ProviderOperationState.succeeded,
    "failed": ProviderOperationState.failed,
    "cancelled": ProviderOperationState.failed,
}


class AnsibleFulfillmentProvider(FulfillmentProvider):
    """Wraps AnsibleJobService/AnsibleService to fulfill a selected resource.

    Depends on AnsibleJobService (not AnsibleService directly — the job
    service already owns that boundary) and ResourcePoolService, plus a
    job-queue provider callable, mirroring VmOperationsService/
    HostOperationsService's existing constructor shape.
    """

    def __init__(
        self,
        *,
        job_service: "AnsibleJobService",
        resource_pool_service: "ResourcePoolService",
        job_queue_provider: Callable[[], "AsyncJobQueue"],
    ) -> None:
        self._job_service = job_service
        self._resource_pool_service = resource_pool_service
        self._job_queue_provider = job_queue_provider

    def _pool_config(self, pool_id: str) -> AnsiblePoolConfig:
        pool = self._resource_pool_service.get_pool(pool_id)
        if pool is None:
            raise ProviderConfigInvalidError(
                f"Resource pool {pool_id!r} no longer exists"
            )
        config = pool.provider_config or {}
        playbook_path = config.get("playbook_path")
        if not playbook_path:
            raise ProviderConfigInvalidError(
                f"Pool {pool_id!r} has no playbook_path configured"
            )
        return AnsiblePoolConfig(
            playbook_path=playbook_path,
            extra_vars=dict(config.get("extra_vars") or {}),
        )

    def _vm_host(self, resource: SettlementResource) -> str:
        vm_host = resource.attributes.get("vm_host")
        if not isinstance(vm_host, str) or not vm_host.strip():
            raise ProviderConfigInvalidError(
                "selected VM settlement resource requires a non-empty vm_host attribute"
            )
        return vm_host

    def _validate_resource(self, resource: SettlementResource) -> AnsiblePoolConfig:
        pool = self._resource_pool_service.get_pool(resource.pool_id)
        if pool is None:
            raise ProviderConfigInvalidError(f"Resource pool {resource.pool_id!r} no longer exists")
        if not bool(getattr(pool, "enabled", True)):
            raise ProviderConfigInvalidError(f"Resource pool {resource.pool_id!r} is disabled")
        if getattr(pool, "provider", resource.provider) != resource.provider:
            raise ProviderConfigInvalidError(
                f"Resource provider {resource.provider!r} does not match pool provider {getattr(pool, 'provider', None)!r}"
            )
        return self._pool_config(resource.pool_id)

    def _validate_extra_vars(self, base_params: AnsibleJobParams, extra_vars: dict[str, Any]) -> None:
        """Reject extra_vars colliding with a built-in field for these params.

        The reserved set is derived dynamically via
        AnsibleJobService.reserved_var_keys(base_params) — the same logic
        AnsibleService uses when actually rendering the vars file — rather
        than a separately hand-maintained list. A hardcoded list can miss
        built-in fields such as ``executor_kind`` and defer a collision until
        asynchronous rendering. ``base_params`` must not have
        ``provider_extra_vars`` set yet —
        reserved_var_keys ignores that field regardless, but passing an
        already-merged params object here would be a caller error.
        """
        if not extra_vars:
            return
        reserved = self._job_service.reserved_var_keys(base_params)
        collisions = sorted(reserved.intersection(extra_vars))
        if collisions:
            raise ProviderConfigInvalidError(
                "provider extra_vars override reserved job variables: " + ", ".join(collisions)
            )

    def validate_create(self, request: PhysicalSettlementRequest, resource: SettlementResource) -> VmFulfillmentRequirements:
        self._validate_resource(resource)
        self._vm_host(resource)
        try:
            requirements = VmFulfillmentRequirements.model_validate(request.requirements)
        except Exception as exc:
            raise ProviderConfigInvalidError(f"invalid VM fulfillment requirements: {exc}") from exc
        return requirements

    def _build_create_params(self, request: PhysicalSettlementRequest, resource: SettlementResource) -> tuple[AnsibleJobParams, VmFulfillmentRequirements]:
        pool_config = self._validate_resource(resource)
        req = self.validate_create(request, resource)
        base_params = AnsibleJobParams(
            vm_host=self._vm_host(resource), vm_action="create", vm_target=req.vm_target,
            image_setup_type=req.image_setup_type, vm_ram=req.vm_ram, vm_vcpus=req.vm_vcpus,
            vm_disk_size=req.vm_disk_size, vm_os_variant=req.vm_os_variant, ssh_pubkey=req.ssh_pubkey,
            gpu_provisioned=req.gpu_provisioned, vm_gpu_count=req.vm_gpu_count,
            vm_gpu_device=req.vm_gpu_device, vm_gpu_devices=req.vm_gpu_devices,
            vm_gpu_partition_size=req.vm_gpu_partition_size, escrow_uid=request.capacity_reservation_id,
            playbook_path=pool_config.playbook_path,
        )
        self._validate_extra_vars(base_params, pool_config.extra_vars)
        params = dataclasses.replace(base_params, provider_extra_vars=pool_config.extra_vars)
        return params, req

    @staticmethod
    def _contract(
        *,
        capacity_reservation_id: str,
        action_kind: str,
        params: AnsibleJobParams,
    ) -> ExecutorActionEnvelope:
        version = 1
        return ExecutorActionEnvelope(
            capacity_reservation_id=capacity_reservation_id,
            deal_ref={},
            executor_kind="vm",
            action_kind=action_kind,
            idempotency_key=(
                f"{capacity_reservation_id}:{action_kind}:v{version}"
            ),
            parameters=dataclasses.asdict(params),
        )

    @staticmethod
    def _decode_prepared(
        prepared: VersionedEnvelope,
        *,
        expected_kind: str,
    ) -> tuple[AnsibleJobParams, ExecutorActionEnvelope, dict[str, Any]]:
        if prepared.kind != expected_kind or prepared.schema_version != 1:
            raise ProviderConfigInvalidError(
                f"unsupported prepared operation {prepared.kind!r} "
                f"version {prepared.schema_version}"
            )
        if not isinstance(prepared.payload, dict):
            raise ProviderConfigInvalidError("prepared operation payload must be an object")
        payload = dict(prepared.payload)
        try:
            params_payload = payload["job_params"]
            contract_payload = payload["contract"]
            if not isinstance(params_payload, dict):
                raise TypeError("job_params must be an object")
            params = AnsibleJobParams(**params_payload)
            contract = ExecutorActionEnvelope.model_validate(contract_payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderConfigInvalidError(
                f"invalid prepared operation payload: {exc}"
            ) from exc
        if contract.parameters != dataclasses.asdict(params):
            raise ProviderConfigInvalidError(
                "prepared operation contract does not match job parameters"
            )
        return params, contract, payload

    def prepare_create(
        self,
        capacity_reservation_id: str,
        fulfillment_request: VersionedEnvelope,
        resource: SettlementResource,
    ) -> VersionedEnvelope:
        if (
            fulfillment_request.kind != "vms.fulfillment"
            or fulfillment_request.schema_version != 1
            or not isinstance(fulfillment_request.payload, dict)
        ):
            raise ProviderConfigInvalidError(
                "unsupported VM fulfillment request kind or schema version"
            )
        request = PhysicalSettlementRequest(
            capacity_reservation_id=capacity_reservation_id,
            market="vms",
            requirements=dict(fulfillment_request.payload),
            resource_id=resource.settlement_resource_id,
        )
        params, requirements = self._build_create_params(request, resource)
        contract = self._contract(
            capacity_reservation_id=capacity_reservation_id,
            action_kind="fulfillment_create",
            params=params,
        )
        return VersionedEnvelope(
            kind="ansible.vm.create",
            schema_version=1,
            payload={
                "job_params": dataclasses.asdict(params),
                "contract": contract.model_dump(mode="json"),
                "vm_target": requirements.vm_target,
            },
        )

    async def dispatch_create(
        self,
        prepared: VersionedEnvelope,
    ) -> FulfillmentResult:
        try:
            params, contract, payload = self._decode_prepared(
                prepared,
                expected_kind="ansible.vm.create",
            )
            response = await self._job_service.submit(
                params,
                self._job_queue_provider(),
                contract=contract,
                credentials_private=True,
            )
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentCreateFailedError(str(exc)) from exc
        metadata = AnsibleFulfillmentMetadata(
            create_job_id=response.job_id,
            current_job_id=response.job_id,
            vm_host=params.vm_host,
            vm_target=str(payload["vm_target"]),
            operation="create",
        )
        return FulfillmentResult(
            provider_metadata=metadata.model_dump(),
            provisioned_resource_refs=(metadata.vm_target,),
        )

    async def create(
        self, request: PhysicalSettlementRequest, resource: SettlementResource
    ) -> FulfillmentResult:
        """Compatibility wrapper over the prepare/dispatch provider contract."""
        fulfillment_request = VersionedEnvelope(
            kind="vms.fulfillment",
            schema_version=1,
            payload=dict(request.requirements),
        )
        return await self.dispatch_create(
            self.prepare_create(
                request.capacity_reservation_id,
                fulfillment_request,
                resource,
            )
        )

    def prepare_teardown(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> VersionedEnvelope:
        metadata = AnsibleFulfillmentMetadata.model_validate(provider_metadata)
        pool_config = self._validate_resource(resource)
        base_params = AnsibleJobParams(
            vm_host=metadata.vm_host,
            vm_action="vm_remove",
            vm_target=metadata.vm_target,
            escrow_uid=capacity_reservation_id,
            playbook_path=pool_config.playbook_path,
        )
        self._validate_extra_vars(base_params, pool_config.extra_vars)
        params = dataclasses.replace(
            base_params,
            provider_extra_vars=pool_config.extra_vars,
        )
        contract = self._contract(
            capacity_reservation_id=capacity_reservation_id,
            action_kind="fulfillment_teardown",
            params=params,
        )
        return VersionedEnvelope(
            kind="ansible.vm.teardown",
            schema_version=1,
            payload={
                "job_params": dataclasses.asdict(params),
                "contract": contract.model_dump(mode="json"),
                "create_metadata": metadata.model_dump(mode="json"),
            },
        )

    async def dispatch_teardown(
        self,
        prepared: VersionedEnvelope,
    ) -> FulfillmentResult:
        try:
            params, contract, payload = self._decode_prepared(
                prepared,
                expected_kind="ansible.vm.teardown",
            )
            metadata = AnsibleFulfillmentMetadata.model_validate(
                payload["create_metadata"]
            )
            response = await self._job_service.submit(
                params,
                self._job_queue_provider(),
                contract=contract,
            )
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentTeardownFailedError(str(exc)) from exc
        updated = metadata.model_copy(update={
            "teardown_job_id": response.job_id,
            "current_job_id": response.job_id,
            "operation": "teardown",
        })
        return FulfillmentResult(provider_metadata=updated.model_dump())

    async def teardown(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> FulfillmentResult:
        """Compatibility wrapper over the prepare/dispatch provider contract."""
        return await self.dispatch_teardown(
            self.prepare_teardown(
                capacity_reservation_id,
                resource,
                provider_metadata,
            )
        )

    async def get_status(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus:
        job_id = provider_metadata.get("current_job_id") or provider_metadata.get("job_id")
        if not job_id:
            return ProviderStatus(
                state=ProviderOperationState.unknown,
                detail="provider_metadata has no job_id",
            )
        try:
            job = self._job_service.get_job(job_id)
        except LookupError:
            # Documented, expected 404 signal from AnsibleJobService.get_job —
            # this is the normal "job is gone" outcome, not a failure.
            return ProviderStatus(
                state=ProviderOperationState.unknown, detail=f"job {job_id} not found"
            )
        except Exception as exc:  # noqa: BLE001
            # Anything else is unexpected and must not be silently folded
            # into "unknown" — surface it.
            raise FulfillmentStatusFailedError(str(exc)) from exc

        state = _JOB_STATUS_TO_OPERATION_STATE.get(
            job.status, ProviderOperationState.unknown
        )
        return ProviderStatus(state=state, detail=job.error)

    async def get_live_credentials(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
        *,
        credential_generation: int,
    ) -> LiveCredentialResult:
        """Rotate and consume VM credentials without storing them in fulfillment."""
        del resource
        metadata = AnsibleFulfillmentMetadata.model_validate(provider_metadata)
        # Create-job credentials are private compatibility material. A result
        # read always rotates, so the original values must never be delivered.
        try:
            self._job_service.consume_private_credentials(metadata.create_job_id)
        except LookupError:
            pass
        params = AnsibleJobParams(
            vm_host=metadata.vm_host,
            vm_action="reset_password",
            vm_target=metadata.vm_target,
            escrow_uid=capacity_reservation_id,
        )
        contract = ExecutorActionEnvelope(
            capacity_reservation_id=capacity_reservation_id,
            deal_ref={},
            executor_kind="vm",
            action_kind="credential_rotation",
            idempotency_key=(
                f"{capacity_reservation_id}:credential_rotation:"
                f"g{credential_generation}:v1"
            ),
            parameters=dataclasses.asdict(params),
        )
        try:
            response = await self._job_service.submit(
                params,
                self._job_queue_provider(),
                contract=contract,
                credentials_private=True,
            )
            job = await self._job_service.wait_for_terminal_job(response.job_id)
            if job.status != "succeeded":
                raise FulfillmentStatusFailedError(
                    job.error or "credential rotation failed"
                )
            consumed = self._job_service.consume_private_credentials(response.job_id)
        except FulfillmentStatusFailedError:
            raise
        except Exception as exc:
            raise FulfillmentStatusFailedError(str(exc)) from exc
        credentials = tuple(
            LiveCredential(
                kind="vm.access.v1",
                schema_version=1,
                payload=credential.model_dump(mode="json", exclude_none=True),
            )
            for credential in consumed.credentials
        )
        if not credentials:
            raise FulfillmentStatusFailedError(
                "credential rotation completed without credentials"
            )
        return LiveCredentialResult(credentials=credentials, rotated=True)
