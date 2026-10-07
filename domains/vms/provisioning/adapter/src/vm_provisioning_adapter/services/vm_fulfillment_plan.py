"""VM's contribution to the compute family's job-backed fulfillment.

A create builds a VM on the KVM host the settled resource is delivered through,
naming the guest from the capacity reservation (``guest_names``): the guest is
the job's ``executor_target`` and the KVM host its ``host_id``. A teardown
removes that guest from that host, as the fulfillment recorded them.

What is VM's here: sizing from the reservation's committed dimensions through
the pool's requirement delegate, the pool's playbook and extra variables, and
the relay. A pool that references a relay leases the VM's remote port on it
when a create is accepted; the lease is the record of where the port is bound,
so a teardown takes the relay from the lease, not from the pool, which may have
been rebound since.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any

from compute_provisioning.job_fulfillment import PreparedJob
from market_core import VersionedEnvelope
from market_fulfillment import ProviderConfigInvalidError, SettlementResource

from vm_provisioning_adapter.guest_names import fulfillment_guest_name
from vm_provisioning_adapter.models.fulfillment_model import (
    AnsiblePoolConfig,
    VmFulfillmentRequirements,
)
from vm_provisioning_adapter.models.jobs_model import VmJobParams
from vm_provisioning_adapter.requirement_delegates import resolve_requirement_delegate

_VM_OFFERING_MODE = "vm"


def _prepared(params: VmJobParams) -> PreparedJob:
    return PreparedJob(
        offering_mode=params.offering_mode,
        action=str(params.executor_action),
        host_id=params.host_id,
        executor_target=str(params.vm_target),
        parameters=dataclasses.asdict(params),
    )


class VmFulfillmentPlan:
    """Prepares a VM's create and teardown jobs for the family's provider."""

    def __init__(
        self,
        *,
        reserved_var_keys: Callable[[VmJobParams], frozenset[str]],
        port_allocator: Any | None = None,
    ) -> None:
        # The variable names a job sets itself (the VM codec's answer), so a
        # pool's extra variables that would replace one are refused when the
        # fulfillment is prepared, before anything is written.
        self._reserved_var_keys = reserved_var_keys
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
        host_id: str,
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
                host_id=host_id,
                pool_id=pool_id,
            )
        except Exception as exc:
            raise ProviderConfigInvalidError(str(exc)) from exc
        return lease.remote_port

    @staticmethod
    def _guest_name(capacity_reservation_id: str) -> str:
        try:
            return fulfillment_guest_name(capacity_reservation_id)
        except ValueError as exc:
            raise ProviderConfigInvalidError(str(exc)) from exc

    @staticmethod
    def _pool_config(pool_config: dict[str, Any]) -> AnsiblePoolConfig:
        try:
            return AnsiblePoolConfig.model_validate(pool_config)
        except Exception as exc:
            raise ProviderConfigInvalidError(
                f"invalid Ansible pool configuration: {exc}"
            ) from exc

    @staticmethod
    def _host_id(resource: SettlementResource) -> str:
        value = resource.host_id
        if not isinstance(value, str) or not value.strip():
            raise ProviderConfigInvalidError(
                "selected VM settlement resource is not delivered through a host"
            )
        return value

    def _validate_extra_vars(
        self,
        params: VmJobParams,
        extra: dict[str, Any],
    ) -> None:
        collisions = sorted(
            self._reserved_var_keys(params).intersection(extra)
        )
        if collisions:
            raise ProviderConfigInvalidError(
                "provider extra_vars override reserved job variables: "
                + ", ".join(collisions)
            )

    def prepare_create(
        self,
        *,
        capacity_reservation_id: str,
        request: VersionedEnvelope[Any],
        resource: SettlementResource,
        pool_config: dict[str, Any],
        allocate: bool,
    ) -> PreparedJob:
        """The create job for a settled VM resource.

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
        if resource.offering_mode != _VM_OFFERING_MODE:
            raise ProviderConfigInvalidError(
                f"VM provider cannot execute offering mode {resource.offering_mode!r}"
            )
        config = self._pool_config(pool_config)
        derived = resolve_requirement_delegate(
            config.requirement_delegate
        ).translate(resource.dimensions)
        host_id = self._host_id(resource)
        # Checking which access path a pool selects is a pure read and belongs
        # in preparation, where a misconfiguration is rejected before anything
        # is written.
        uses_relay = self._validate_access_path(config)
        # Leasing is not. Validation prepares in order to decide whether a
        # request *would* be accepted, so allocating here would let a
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
                host_id=host_id,
                pool_id=resource.pool_id,
            )
            if uses_relay and allocate
            else None
        )
        params = VmJobParams(
            host_id=host_id,
            vm_action="create",
            offering_mode=resource.offering_mode,
            vm_target=self._guest_name(capacity_reservation_id),
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
        return _prepared(dataclasses.replace(params, provider_extra_vars=config.extra_vars))

    def prepare_teardown(
        self,
        *,
        capacity_reservation_id: str,
        resource: SettlementResource,
        host_id: str,
        executor_target: str,
        create_parameters: Mapping[str, Any],
        pool_config: dict[str, Any],
    ) -> PreparedJob:
        """The job removing the guest the create recorded, from its host.

        Reads nothing from the create's parameters: the target is the
        fulfillment's, the playbook the pool's, and the relay the lease's.
        """
        del create_parameters
        config = self._pool_config(pool_config)
        params = VmJobParams(
            host_id=host_id,
            vm_action="vm_remove",
            offering_mode=resource.offering_mode,
            vm_target=executor_target,
            escrow_uid=capacity_reservation_id,
            playbook_path=config.playbook_path,
            relay_id=self._leased_relay_id(capacity_reservation_id),
        )
        self._validate_extra_vars(params, config.extra_vars)
        return _prepared(dataclasses.replace(params, provider_extra_vars=config.extra_vars))


__all__ = ["VmFulfillmentPlan"]
