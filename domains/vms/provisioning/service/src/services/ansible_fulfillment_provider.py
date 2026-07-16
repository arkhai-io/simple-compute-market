"""Ansible implementation of FulfillmentProvider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from compute_provisioning import PhysicalSettlementRequest, SettlementResource
from models.jobs_model import AnsibleJobParams
from models.fulfillment_model import AnsibleFulfillmentMetadata, VmFulfillmentRequirements
from market_resource_pools import (
    FulfillmentCreateFailedError,
    FulfillmentProvider,
    FulfillmentResult,
    FulfillmentStatusFailedError,
    FulfillmentTeardownFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    ProviderStatus,
)

if TYPE_CHECKING:
    from market_resource_pools import ResourcePoolService
    from services.async_job_queue import AsyncJobQueue
    from services.job_service import AnsibleJobService


@dataclass(frozen=True)
class AnsiblePoolConfig:
    """Provider-local, typed view of a pool's Ansible provider configuration.

    Deliberately narrower than the persisted provider_config dict: no
    ``inventory_group`` (see Pools 3 design.md Decision 6 — it's not used for
    dispatch; concrete placement is entirely PhysicalSettlementScheduler's
    job, and an inventory group would be a second, conflicting scheduler).
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

    @staticmethod
    def _validate_extra_vars(extra_vars: dict[str, Any]) -> None:
        reserved = {
            "vm_host", "vm_action", "vm_target", "vm_ram", "vm_vcpus",
            "vm_disk_size", "vm_os_variant", "ssh_pubkey", "escrow_uid",
        }
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
        self._validate_extra_vars(pool_config.extra_vars)
        req = self.validate_create(request, resource)
        return AnsibleJobParams(
            vm_host=self._vm_host(resource), vm_action="create", vm_target=req.vm_target,
            image_setup_type=req.image_setup_type, vm_ram=req.vm_ram, vm_vcpus=req.vm_vcpus,
            vm_disk_size=req.vm_disk_size, vm_os_variant=req.vm_os_variant, ssh_pubkey=req.ssh_pubkey,
            gpu_provisioned=req.gpu_provisioned, vm_gpu_count=req.vm_gpu_count,
            vm_gpu_device=req.vm_gpu_device, vm_gpu_devices=req.vm_gpu_devices,
            vm_gpu_partition_size=req.vm_gpu_partition_size, escrow_uid=request.allocation_id,
            playbook_path=pool_config.playbook_path, provider_extra_vars=pool_config.extra_vars,
        ), req

    async def create(
        self, request: PhysicalSettlementRequest, resource: SettlementResource
    ) -> FulfillmentResult:
        try:
            params, req = self._build_create_params(request, resource)
            response = await self._job_service.submit(params, self._job_queue_provider())
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentCreateFailedError(str(exc)) from exc
        metadata = AnsibleFulfillmentMetadata(
            create_job_id=response.job_id, current_job_id=response.job_id,
            vm_host=params.vm_host, vm_target=req.vm_target, operation="create",
        )
        return FulfillmentResult(provider_metadata=metadata.model_dump())

    async def teardown(
        self, allocation_id: str, resource: SettlementResource, provider_metadata: dict[str, Any]
    ) -> FulfillmentResult:
        try:
            metadata = AnsibleFulfillmentMetadata.model_validate(provider_metadata)
            pool_config = self._validate_resource(resource)
            self._validate_extra_vars(pool_config.extra_vars)
            params = AnsibleJobParams(
                vm_host=metadata.vm_host, vm_action="vm_remove", vm_target=metadata.vm_target,
                escrow_uid=allocation_id, playbook_path=pool_config.playbook_path,
                provider_extra_vars=pool_config.extra_vars,
            )
            response = await self._job_service.submit(params, self._job_queue_provider())
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentTeardownFailedError(str(exc)) from exc
        updated = metadata.model_copy(update={
            "teardown_job_id": response.job_id, "current_job_id": response.job_id, "operation": "teardown"
        })
        return FulfillmentResult(provider_metadata=updated.model_dump())

    async def get_status(
        self,
        allocation_id: str,
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
