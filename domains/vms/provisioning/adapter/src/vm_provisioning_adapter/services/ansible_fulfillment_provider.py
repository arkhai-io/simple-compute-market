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
    VmConnectionInfo,
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
from vm_provisioning_adapter.requirement_delegates import resolve_requirement_delegate

_VM_EXECUTOR_KIND = "vm"

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
        port_allocator: Any | None = None,
    ) -> None:
        self._job_service = job_service
        self._job_queue_provider = job_queue_provider
        # Optional so a pool with no relay — the direct-NAT path — needs no
        # allocator at all. A pool that does reference a relay and finds no
        # allocator is rejected rather than dispatched without a port.
        self._port_allocator = port_allocator

    @staticmethod
    def _validate_access_path(config: AnsiblePoolConfig) -> bool:
        """Decide which access path this pool selects, refusing to select none.

        Exactly one of two paths must apply: direct NAT for a pool with no
        relay, or a relay tunnel for a pool with one. The failure this replaces
        was a configuration satisfying neither, which produced a VM with no
        external route and reported success.

        Every check here is answerable from configuration before any host is
        touched, and each names what is missing. A rejection reading only
        "misconfigured" would reproduce the diagnostic problem this change
        exists to remove — a relay refusing a proxy asynchronously in a log.
        """
        if not config.relay_id:
            return False

        missing = [
            name
            for name, value in (
                ("relay address", config.relay_addr),
                ("port window start", config.vm_port_range_start),
                ("port window size", config.vm_port_range_count),
                ("admission token", config.relay_token),
            )
            if not value
        ]
        if missing:
            raise ProviderConfigInvalidError(
                f"pool references relay {config.relay_id!r}, but the relay is "
                f"unusable: no {', no '.join(missing)}. A relay that is disabled, "
                "has no allocation window, or has no token configured cannot "
                "carry a VM tunnel, and a VM created against it would have no "
                "external route."
            )
        return True

    def _leased_relay_id(self, capacity_reservation_id: str) -> str | None:
        """The relay this fulfillment's port was leased on, if any.

        Returns None for a direct-NAT VM and for a lease already released, both
        of which mean there is no relay work left to do at teardown.
        """
        if self._port_allocator is None:
            return None
        lease = self._port_allocator.find_active_lease(
            owner_kind="fulfillment", owner_id=capacity_reservation_id
        )
        return None if lease is None else lease.relay_id

    def _lease_remote_port(
        self,
        *,
        config: AnsiblePoolConfig,
        capacity_reservation_id: str,
        vm_host: str,
        pool_id: str | None,
    ) -> int:
        """Lease a remote port on the relay this pool references.

        ``pool_id`` is recorded on the lease and is not decoration: the rule
        refusing a pool repoint while its hosts hold tunnels finds those
        tunnels by pool, so a lease without one leaves that rule unable to see
        anything and silently permissive.
        """
        if self._port_allocator is None:
            raise ProviderConfigInvalidError(
                f"pool references relay {config.relay_id!r} but this provider was "
                "built without a port allocator, so no remote port can be leased"
            )
        try:
            lease = self._port_allocator.allocate(
                relay_id=config.relay_id,
                owner_kind="fulfillment",
                owner_id=capacity_reservation_id,
                host_name=vm_host,
                pool_id=pool_id,
            )
        except Exception as exc:
            raise ProviderConfigInvalidError(str(exc)) from exc
        return lease.remote_port

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
        allocate: bool = True,
    ) -> VersionedEnvelope[Any]:
        """Build the accepted operation for a VM creation.

        ``allocate=False`` makes preparation a pure function of its inputs, for
        the validation path: every rejection still happens, and no durable
        state is written.
        """
        try:
            requirements = VmFulfillmentRequirements.model_validate(request.payload)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid VM fulfillment requirements: {exc}"
            ) from exc

        if resource.executor_kind != _VM_EXECUTOR_KIND:
            raise ProviderConfigInvalidError(
                f"VM provider cannot execute offering mode "
                f"{resource.executor_kind!r}"
            )
        config = self._pool_config(pool_config)
        derived = resolve_requirement_delegate(
            config.requirement_delegate
        ).translate(resource.dimensions)
        vm_host = self._vm_host(resource)
        # Checking which access path a pool selects is a pure read and belongs
        # in preparation, where a misconfiguration is rejected before anything
        # is written.
        uses_relay = self._validate_access_path(config)
        # Leasing is not. `validate_fulfillment` prepares in order to decide
        # whether a request *would* be accepted, so allocating here would let a
        # validation-only call consume a durable port — and repeated validation
        # exhaust a finite window without a single accepted fulfillment.
        #
        # Still allocated before dispatch, just after acceptance rather than
        # before it: a crash between allocation and dispatch must not leave a
        # port bound on the relay that no record claims.
        remote_port = (
            self._lease_remote_port(
                config=config,
                capacity_reservation_id=capacity_reservation_id,
                vm_host=vm_host,
                pool_id=resource.pool_id,
            )
            if uses_relay and allocate
            else None
        )
        params = AnsibleJobParams(
            vm_host=vm_host,
            vm_action="create",
            executor_kind=resource.executor_kind,
            vm_target=requirements.vm_target,
            image_setup_type=requirements.image_setup_type,
            vm_ram=derived.get("vm_ram", config.default_vm_ram),
            vm_vcpus=derived.get("vm_vcpus", config.default_vm_vcpus),
            vm_disk_size=derived.get("vm_disk_size", config.default_vm_disk_size),
            vm_os_variant=requirements.vm_os_variant,
            ssh_pubkey=requirements.ssh_pubkey,
            gpu_provisioned=derived.get("gpu_provisioned"),
            vm_gpu_count=derived.get("vm_gpu_count"),
            vm_gpu_device=requirements.vm_gpu_device,
            vm_gpu_devices=requirements.vm_gpu_devices,
            vm_gpu_partition_size=requirements.vm_gpu_partition_size,
            # The reference and the leased port, never the endpoint or the
            # token: this becomes a persisted, readable snapshot. Resolution
            # happens at execution — see services/relay_execution.py.
            relay_id=config.relay_id if uses_relay else None,
            vm_remote_port=remote_port,
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
                executor_kind=params.executor_kind,
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
        # The relay comes from the lease, not from the pool. The pool may have
        # been rebound since this VM was created, and the lease is the only
        # record of where its port was actually bound — resolving from pool
        # configuration would reload the wrong host client and release a port
        # against a relay it never occupied.
        relay_id = self._leased_relay_id(settlement_result.capacity_reservation_id)
        params = AnsibleJobParams(
            vm_host=metadata.vm_host,
            vm_action="vm_remove",
            executor_kind=settlement_result.resource.executor_kind,
            vm_target=metadata.vm_target,
            escrow_uid=settlement_result.capacity_reservation_id,
            playbook_path=config.playbook_path,
            relay_id=relay_id,
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
                executor_kind=params.executor_kind,
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

        # Best-effort: the job's parsed result payload carries VM
        # identity/connection metadata (VmConnectionInfo's fields) beyond
        # what credentials alone provide. A missing or unreadable result
        # must not fail an otherwise-successful credential fetch -- every
        # field on VmConnectionInfo is optional for exactly this reason.
        result: dict[str, Any] = {}
        try:
            job = self._job_service.get_job(job_id)
            if isinstance(job.result, dict):
                result = job.result
        except Exception as exc:
            logger.warning(
                "Could not read job %s result for fulfillment metadata: %s",
                job_id, exc,
            )

        output_ids = tuple(
            resource.provisioned_resource_id for resource in provisioned_resources
        )
        connection_info = VmConnectionInfo(
            vm_name=result.get("vm_name"),
            host=result.get("host"),
            timestamp=result.get("timestamp"),
            tenant_user=result.get("tenant_user"),
            vm_ip_internal=result.get("vm_ip_internal"),
            ssh_port=result.get("ssh_port"),
        )
        return build_vm_fulfillment_result(
            provisioned_resources,
            tuple(
                VmFulfillmentCredential(
                    role=credential.role,
                    password=credential.password,
                    ssh_commands=credential.ssh_commands,
                    ssh_key_path_host=credential.ssh_key_path_host,
                    key_type=credential.key_type,
                    provisioned_resource_ids=output_ids,
                )
                for credential in response.credentials
            ),
            connection_info=connection_info,
        )
