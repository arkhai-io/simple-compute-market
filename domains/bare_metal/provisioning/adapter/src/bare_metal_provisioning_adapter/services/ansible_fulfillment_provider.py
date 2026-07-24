"""Bare-metal Ansible fulfillment for scheduler-selected machines."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    BareMetalProvisionPayload,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    bare_metal_executor_ref,
)
from compute_provisioning import ExecutorActionEnvelope
from market_fulfillment import (
    FulfillmentCreateFailedError,
    FulfillmentProvider,
    FulfillmentResult,
    FulfillmentStatusFailedError,
    FulfillmentTeardownFailedError,
    ProviderConfigInvalidError,
    ProviderOperationState,
    ProviderStatus,
    SettlementResource,
    VersionedEnvelope,
)
from bare_metal_provisioning_adapter.models.fulfillment_model import (
    BareMetalAnsibleJobParams,
    BareMetalFulfillmentMetadata,
)


class BareMetalJobService(Protocol):
    async def submit(self, params, job_queue, *, contract): ...
    def get_job(self, job_id: str): ...


class BareMetalResourcePoolService(Protocol):
    def get_pool(self, pool_id: str): ...


@dataclass(frozen=True)
class BareMetalAnsiblePoolConfig:
    playbook_path: str
    extra_vars: dict[str, Any]


_JOB_STATES = {
    "queued": ProviderOperationState.pending,
    "running": ProviderOperationState.pending,
    "succeeded": ProviderOperationState.succeeded,
    "failed": ProviderOperationState.failed,
    "cancelled": ProviderOperationState.failed,
}


class BareMetalAnsibleFulfillmentProvider(FulfillmentProvider):
    """Grant and reclaim access only on the selected bare-metal resource."""

    def __init__(
        self,
        *,
        job_service: BareMetalJobService,
        resource_pool_service: BareMetalResourcePoolService,
        job_queue_provider: Callable[[], Any],
    ) -> None:
        self._job_service = job_service
        self._resource_pool_service = resource_pool_service
        self._job_queue_provider = job_queue_provider

    def _validate_resource(
        self, resource: SettlementResource
    ) -> tuple[str, str, BareMetalAnsiblePoolConfig]:
        if resource.resource_kind != "bare_metal":
            raise ProviderConfigInvalidError(
                "bare-metal provider requires resource_kind='bare_metal'"
            )
        pool = self._resource_pool_service.get_pool(resource.pool_id)
        if pool is None or not bool(getattr(pool, "enabled", True)):
            raise ProviderConfigInvalidError(
                f"Resource pool {resource.pool_id!r} is missing or disabled"
            )
        if getattr(pool, "provider", resource.provider) != resource.provider:
            raise ProviderConfigInvalidError(
                f"Resource provider {resource.provider!r} does not match its pool"
            )
        config = dict(getattr(pool, "provider_config", None) or {})
        playbook_path = config.get("playbook_path")
        if not isinstance(playbook_path, str) or not playbook_path.strip():
            raise ProviderConfigInvalidError(
                f"Pool {resource.pool_id!r} has no playbook_path configured"
            )
        attributes = dict(resource.attributes)
        publication = attributes.get("bare_metal_publication")
        if isinstance(publication, dict):
            attributes = {**attributes, **publication}
        machine_id = attributes.get("machine_id")
        physical_host_id = attributes.get("physical_host_id")
        if not isinstance(machine_id, str) or not machine_id.strip():
            raise ProviderConfigInvalidError(
                "selected bare-metal resource requires machine_id"
            )
        if not isinstance(physical_host_id, str) or not physical_host_id.strip():
            raise ProviderConfigInvalidError(
                "selected bare-metal resource requires physical_host_id"
            )
        return machine_id, physical_host_id, BareMetalAnsiblePoolConfig(
            playbook_path=playbook_path,
            extra_vars=dict(config.get("extra_vars") or {}),
        )

    def _params(
        self,
        *,
        capacity_reservation_id: str,
        resource: SettlementResource,
        action: str,
        ssh_public_key: str | None,
    ) -> tuple[BareMetalAnsibleJobParams, str, str]:
        machine_id, physical_host_id, config = self._validate_resource(resource)
        access_ref = (
            {"ssh_public_key": ssh_public_key} if ssh_public_key is not None else {}
        )
        base = BareMetalAnsibleJobParams(
            vm_host=machine_id,
            vm_action=action,
            vm_target=machine_id,
            executor_kind=BARE_METAL_EXECUTOR_KIND,
            executor_action=action,
            executor_target=machine_id,
            executor_ref=bare_metal_executor_ref(
                physical_host_id,
                access_ref=access_ref or None,
            ),
            escrow_uid=capacity_reservation_id,
            physical_host_id=physical_host_id,
            ssh_public_key=ssh_public_key,
            access_ref=access_ref or None,
            playbook_path=config.playbook_path,
        )
        collisions = sorted(
            {field.name for field in dataclasses.fields(base)}.intersection(config.extra_vars)
        )
        if collisions:
            raise ProviderConfigInvalidError(
                "provider extra_vars override reserved job variables: "
                + ", ".join(collisions)
            )
        return (
            dataclasses.replace(base, provider_extra_vars=config.extra_vars),
            machine_id,
            physical_host_id,
        )

    @staticmethod
    def _contract(
        capacity_reservation_id: str,
        action_kind: str,
        params: BareMetalAnsibleJobParams,
    ) -> ExecutorActionEnvelope:
        return ExecutorActionEnvelope(
            capacity_reservation_id=capacity_reservation_id,
            deal_ref={},
            executor_kind=BARE_METAL_EXECUTOR_KIND,
            action_kind=action_kind,
            idempotency_key=f"{capacity_reservation_id}:{action_kind}:v1",
            parameters=dataclasses.asdict(params),
        )

    @staticmethod
    def _prepared(
        *,
        kind: str,
        params: BareMetalAnsibleJobParams,
        contract: ExecutorActionEnvelope,
        metadata: dict[str, Any],
    ) -> VersionedEnvelope:
        return VersionedEnvelope(
            kind=kind,
            schema_version=1,
            payload={
                "job_params": dataclasses.asdict(params),
                "contract": contract.model_dump(mode="json"),
                "metadata": metadata,
            },
        )

    @staticmethod
    def _decode(
        prepared: VersionedEnvelope,
        expected_kind: str,
    ) -> tuple[BareMetalAnsibleJobParams, ExecutorActionEnvelope, dict[str, Any]]:
        if prepared.kind != expected_kind or prepared.schema_version != 1:
            raise ProviderConfigInvalidError(
                f"unsupported prepared operation {prepared.kind!r}"
            )
        try:
            payload = dict(prepared.payload)
            params = BareMetalAnsibleJobParams(**payload["job_params"])
            contract = ExecutorActionEnvelope.model_validate(payload["contract"])
            metadata = dict(payload["metadata"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderConfigInvalidError(
                f"invalid prepared bare-metal operation: {exc}"
            ) from exc
        if contract.parameters != dataclasses.asdict(params):
            raise ProviderConfigInvalidError(
                "prepared operation contract does not match job parameters"
            )
        return params, contract, metadata

    def prepare_create(
        self,
        capacity_reservation_id: str,
        fulfillment_request: VersionedEnvelope,
        resource: SettlementResource,
    ) -> VersionedEnvelope:
        if (
            fulfillment_request.kind != "bare_metal.v1"
            or fulfillment_request.schema_version != 1
        ):
            raise ProviderConfigInvalidError(
                "unsupported bare-metal fulfillment request"
            )
        try:
            request = BareMetalProvisionPayload.model_validate(
                fulfillment_request.payload
            )
        except Exception as exc:
            raise ProviderConfigInvalidError(
                "invalid bare-metal fulfillment request"
            ) from exc
        params, machine_id, physical_host_id = self._params(
            capacity_reservation_id=capacity_reservation_id,
            resource=resource,
            action=NODE_GRANT_ACCESS_ACTION,
            ssh_public_key=request.ssh_public_key,
        )
        contract = self._contract(
            capacity_reservation_id, "fulfillment_create", params
        )
        return self._prepared(
            kind="ansible.bare_metal.create",
            params=params,
            contract=contract,
            metadata={
                "machine_id": machine_id,
                "physical_host_id": physical_host_id,
            },
        )

    async def dispatch_create(self, prepared: VersionedEnvelope) -> FulfillmentResult:
        try:
            params, contract, metadata = self._decode(
                prepared, "ansible.bare_metal.create"
            )
            response = await self._job_service.submit(
                params, self._job_queue_provider(), contract=contract
            )
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentCreateFailedError(
                "bare-metal provider create failed"
            ) from exc
        state = BareMetalFulfillmentMetadata(
            create_job_id=response.job_id,
            current_job_id=response.job_id,
            machine_id=metadata["machine_id"],
            physical_host_id=metadata["physical_host_id"],
            operation="create",
        )
        return FulfillmentResult(
            provider_metadata=state.model_dump(mode="json"),
            provisioned_resource_refs=(state.machine_id,),
        )

    def prepare_teardown(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> VersionedEnvelope:
        metadata = BareMetalFulfillmentMetadata.model_validate(provider_metadata)
        params, machine_id, physical_host_id = self._params(
            capacity_reservation_id=capacity_reservation_id,
            resource=resource,
            action=NODE_RECLAIM_ACCESS_ACTION,
            ssh_public_key=None,
        )
        if (machine_id, physical_host_id) != (
            metadata.machine_id,
            metadata.physical_host_id,
        ):
            raise ProviderConfigInvalidError(
                "selected resource identity differs from create metadata"
            )
        return self._prepared(
            kind="ansible.bare_metal.teardown",
            params=params,
            contract=self._contract(
                capacity_reservation_id, "fulfillment_teardown", params
            ),
            metadata=metadata.model_dump(mode="json"),
        )

    async def dispatch_teardown(
        self, prepared: VersionedEnvelope
    ) -> FulfillmentResult:
        try:
            params, contract, raw_metadata = self._decode(
                prepared, "ansible.bare_metal.teardown"
            )
            metadata = BareMetalFulfillmentMetadata.model_validate(raw_metadata)
            response = await self._job_service.submit(
                params, self._job_queue_provider(), contract=contract
            )
        except ProviderConfigInvalidError:
            raise
        except Exception as exc:
            raise FulfillmentTeardownFailedError(
                "bare-metal provider teardown failed"
            ) from exc
        updated = metadata.model_copy(
            update={
                "teardown_job_id": response.job_id,
                "current_job_id": response.job_id,
                "operation": "teardown",
            }
        )
        return FulfillmentResult(provider_metadata=updated.model_dump(mode="json"))

    async def get_status(
        self,
        capacity_reservation_id: str,
        resource: SettlementResource,
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus:
        del capacity_reservation_id, resource
        metadata = BareMetalFulfillmentMetadata.model_validate(provider_metadata)
        try:
            job = self._job_service.get_job(metadata.current_job_id)
        except LookupError:
            return ProviderStatus(
                state=ProviderOperationState.unknown,
                detail=f"job {metadata.current_job_id} not found",
            )
        except Exception as exc:
            raise FulfillmentStatusFailedError(
                "bare-metal provider status failed"
            ) from exc
        state = _JOB_STATES.get(job.status, ProviderOperationState.unknown)
        return ProviderStatus(
            state=state,
            detail=(
                "provider job failed"
                if state is ProviderOperationState.failed
                else None
            ),
        )
