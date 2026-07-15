"""Ansible implementation of FulfillmentProvider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from compute_provisioning import PhysicalSettlementRequest, SettlementResource
from models.jobs_model import AnsibleJobParams
from services.fulfillment_provider import (
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
        # No production caller exists yet for this resolution (see
        # proposal.md, "Explicitly Deferred This Round"), so the exact
        # shape of resource.attributes for a live caller is not yet
        # constrained. Prefer an explicit vm_host attribute if present,
        # falling back to the settlement resource id as the host
        # identifier otherwise. Revisit once pools-7 supplies a real
        # caller and real attribute shapes.
        return str(resource.attributes.get("vm_host", resource.settlement_resource_id))

    def _build_params(
        self,
        *,
        vm_action: str,
        request: PhysicalSettlementRequest | None,
        resource: SettlementResource,
    ) -> AnsibleJobParams:
        pool_config = self._pool_config(resource.pool_id)
        return AnsibleJobParams(
            vm_host=self._vm_host(resource),
            vm_action=vm_action,
            escrow_uid=(request.allocation_id if request else None),
            playbook_path=pool_config.playbook_path,
            provider_extra_vars=pool_config.extra_vars,
        )

    async def create(
        self,
        request: PhysicalSettlementRequest,
        resource: SettlementResource,
    ) -> FulfillmentResult:
        try:
            params = self._build_params(
                vm_action="create", request=request, resource=resource
            )
            response = await self._job_service.submit(params, self._job_queue_provider())
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:  # noqa: BLE001 — wrap, don't swallow
            raise FulfillmentCreateFailedError(str(exc)) from exc
        return FulfillmentResult(
            provider_metadata={"job_id": response.job_id, "operation": "create"}
        )

    async def teardown(
        self,
        allocation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> FulfillmentResult:
        try:
            params = self._build_params(
                vm_action="vm_remove", request=None, resource=resource
            )
            response = await self._job_service.submit(params, self._job_queue_provider())
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise FulfillmentTeardownFailedError(str(exc)) from exc
        return FulfillmentResult(
            provider_metadata={"job_id": response.job_id, "operation": "teardown"}
        )

    async def get_status(
        self,
        allocation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus:
        job_id = provider_metadata.get("job_id")
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
