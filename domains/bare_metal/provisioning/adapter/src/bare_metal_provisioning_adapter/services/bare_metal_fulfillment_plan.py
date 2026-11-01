"""Bare metal's contribution to the compute family's job-backed fulfillment.

A grant installs the buyer's key for a tenant account on the whole host the
lease sells; the reclaim that undoes it is prepared from the grant job's own
parameters, so it removes exactly the access the grant gave, on the same host,
with the accepted bounded policy or the current legacy reclaim policy. Each job carries the access
playbook the deployment configures when the job is prepared, so a later
configuration change never rewrites an accepted operation.

The sold unit is one whole host: the job runs against it and acts on it, so its
``host_id`` is both where the job runs and its ``executor_target``. The
machine's ``physical_host_id`` is the declaration's cross-mode identity; it is
checked here against the selected resource and travels in the job's parameters
for the access role, but it names nothing the fulfillment tracks.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
    BareMetalMaterialization,
    NODE_GRANT_ACCESS_ACTION,
    NODE_RECLAIM_ACCESS_ACTION,
    bare_metal_executor_ref,
    materialization_to_access_grant,
)
from compute_provisioning.job_fulfillment import PreparedJob
from compute_provisioning.relays import check_relay_usable, reservation_lease_end
from market_core import VersionedEnvelope
from market_fulfillment import ProviderConfigInvalidError, SettlementResource
from pydantic import ValidationError

from bare_metal_provisioning_adapter.codec import BareMetalJobParams, reclaim_policy_from


def _access_value(access_ref: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = access_ref.get(key)
        if value:
            return str(value)
    return None


def _validate_pool_config(pool_config: Mapping[str, Any]) -> None:
    # The execution read contributes resolved relay fields; pool writes accept
    # only its reference, through the family configuration handler.
    allowed = {
        "relay_id", "relay_addr", "relay_port", "relay_token",
        "vm_port_range_start", "vm_port_range_count", "grant_key_id",
    }
    if set(pool_config) - allowed:
        raise ProviderConfigInvalidError(
            "bare-metal provider does not accept pool-local configuration"
        )


def _publication(resource: SettlementResource) -> Mapping[str, Any]:
    publication = resource.attributes.get("bare_metal_publication")
    if not isinstance(publication, dict) or publication.get("enabled") is not True:
        raise ProviderConfigInvalidError(
            "selected bare-metal resource has no enabled publication view"
        )
    return publication


def _resource_host_id(resource: SettlementResource) -> str:
    """The host the selected resource is delivered through."""
    _publication(resource)
    value = resource.host_id
    if not isinstance(value, str) or not value.strip():
        raise ProviderConfigInvalidError(
            "selected bare-metal resource is not delivered through a host"
        )
    return value


def _resource_physical_host_id(resource: SettlementResource) -> str:
    """The physical machine the selected resource occupies.

    Read from the declaration's top level, where the ledger's cross-mode
    accounting reads it, so the plan and the admission rule cannot disagree
    about which machine a resource is.
    """
    _publication(resource)
    value = resource.attributes.get("physical_host_id")
    if not isinstance(value, str) or not value.strip():
        raise ProviderConfigInvalidError(
            "selected bare-metal resource requires a non-empty physical_host_id"
        )
    return value


def _require_bare_metal(resource: SettlementResource) -> None:
    if resource.offering_mode != BARE_METAL_OFFERING_MODE:
        raise ProviderConfigInvalidError(
            f"bare-metal provider cannot execute offering mode {resource.offering_mode!r}"
        )


class BareMetalFulfillmentPlan:
    """Prepares a grant for a settled whole host, and the reclaim that undoes it."""

    def __init__(
        self,
        *,
        playbook_path: str | os.PathLike[str],
        reclaim_policy: str | None = None,
        working_data_policy_id: str | None = None,
        port_allocator: Any | None = None,
        lease_end: Callable[[Any, str], datetime | None] = reservation_lease_end,
    ) -> None:
        self._playbook_path = os.fspath(playbook_path)
        self._port_allocator = port_allocator
        self._lease_end = lease_end
        # Validated here, at composition, so a deployment configured with a
        # policy the access role does not implement refuses to start.
        self._reclaim_policy = reclaim_policy_from(reclaim_policy)
        self._working_data_policy_id = working_data_policy_id
        if self._reclaim_policy == "bounded_working_data" and (
            not isinstance(working_data_policy_id, str) or not working_data_policy_id.strip()
        ):
            raise ValueError("bounded cleanup requires bare_metal_working_data_policy_id")

    def prepare_create(
        self,
        *,
        capacity_reservation_id: str,
        request: VersionedEnvelope[Any],
        resource: SettlementResource,
        pool_config: dict[str, Any],
        allocate: bool,
        db: Any | None = None,
    ) -> PreparedJob:
        _validate_pool_config(pool_config)
        _require_bare_metal(resource)
        protected = {
            "reclaim_policy", "working_data_policy_id", "cleanup_roots", "scratch_roots",
            "ipc_roots", "home", "home_parent", "uid", "gid", "ledger", "policy",
            "bare_metal_reclaim_policy", "bare_metal_working_data_policy_id",
            "capacity_reservation_id", "bare_metal_capacity_reservation_id",
        }
        payload = request.payload
        if isinstance(payload, Mapping):
            access = payload.get("access_ref")
            if protected.intersection(payload) or (
                isinstance(access, Mapping) and protected.intersection(access)
            ):
                raise ProviderConfigInvalidError("invalid bare-metal fulfillment requirements: cleanup authority is operator-selected")
        try:
            materialization = BareMetalMaterialization.model_validate(payload)
        except ValidationError as exc:
            raise ProviderConfigInvalidError(
                f"invalid bare-metal fulfillment requirements: {exc}"
            ) from exc
        host_id = _resource_host_id(resource)
        if materialization.host_id != host_id:
            raise ProviderConfigInvalidError(
                "materialization host_id does not match the selected resource"
            )
        if materialization.physical_host_id != _resource_physical_host_id(resource):
            raise ProviderConfigInvalidError(
                "materialization physical_host_id does not match the selected resource"
            )
        grant = materialization_to_access_grant(
            materialization, capacity_reservation_id=capacity_reservation_id
        )
        access_ref = dict(grant.access_ref or {})
        relay_id = pool_config.get("relay_id")
        remote_port = None
        if relay_id:
            check_relay_usable(relay_id, pool_config)
            if db is None:
                raise ProviderConfigInvalidError(
                    "relay port allocation requires the fulfillment acceptance session"
                )
            lease_end = self._lease_end(db, capacity_reservation_id)
            if lease_end is None:
                raise ProviderConfigInvalidError(
                    f"reservation {capacity_reservation_id!r} states no lease end"
                )
            if self._port_allocator is None:
                raise ProviderConfigInvalidError("relay requires a port allocator")
            # Validation reads the same inputs without claiming a durable port.
            # Acceptance allocates in its own transaction, so rejection rolls it back.
            if allocate:
                try:
                    lease = self._port_allocator.allocate_in_session(
                        db, relay_id=relay_id, owner_kind="fulfillment",
                        owner_id=capacity_reservation_id, lease_ends_at=lease_end,
                        host_id=host_id, pool_id=resource.pool_id,
                    )
                except Exception as exc:
                    raise ProviderConfigInvalidError(str(exc)) from exc
                remote_port = lease.remote_port
        params = BareMetalJobParams(
            capacity_reservation_id=capacity_reservation_id,
            relay_id=relay_id,
            remote_port=remote_port,
            action=NODE_GRANT_ACCESS_ACTION,
            host_id=host_id,
            physical_host_id=grant.physical_host_id,
            escrow_uid=grant.escrow_uid,
            executor_ref=bare_metal_executor_ref(
                grant.physical_host_id, access_ref=access_ref or None
            ),
            access_ref=access_ref or None,
            ssh_user=_access_value(access_ref, "ssh_user", "user"),
            ssh_public_key=_access_value(
                access_ref, "ssh_public_key", "ssh_pubkey", "public_key"
            ),
            reclaim_policy=(self._reclaim_policy if self._reclaim_policy == "bounded_working_data" else None),
            working_data_policy_id=(self._working_data_policy_id if self._reclaim_policy == "bounded_working_data" else None),
            playbook_path=self._playbook_path,
        )
        return PreparedJob(
            offering_mode=BARE_METAL_OFFERING_MODE,
            action=NODE_GRANT_ACCESS_ACTION,
            host_id=host_id,
            executor_target=host_id,
            parameters=params.model_dump(mode="json"),
        )

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
        _validate_pool_config(pool_config)
        _require_bare_metal(resource)
        try:
            grant = BareMetalJobParams.model_validate(dict(create_parameters))
        except ValidationError as exc:
            raise ProviderConfigInvalidError(
                f"the create job's parameters are not a bare-metal grant: {exc}"
            ) from exc
        if grant.action != NODE_GRANT_ACCESS_ACTION:
            raise ProviderConfigInvalidError(
                f"the create job ran {grant.action!r}, not a grant"
            )
        if grant.host_id != host_id or _resource_host_id(resource) != host_id:
            raise ProviderConfigInvalidError(
                "the grant, the fulfillment, and the selected resource name different hosts"
            )
        if grant.physical_host_id != _resource_physical_host_id(resource):
            raise ProviderConfigInvalidError(
                "the grant's physical_host_id does not match the selected resource"
            )
        bounded = grant.reclaim_policy == "bounded_working_data"
        if bounded and grant.capacity_reservation_id != capacity_reservation_id:
            raise ProviderConfigInvalidError("bounded grant reservation does not match teardown")
        if not bounded and self._reclaim_policy == "bounded_working_data":
            raise ProviderConfigInvalidError("cannot adopt a legacy grant into bounded cleanup")
        # Bounded grants retain their accepted policy; legacy policies keep
        # their existing deployment-selected reclaim behavior.
        lease = (
            self._port_allocator.find_active_lease(
                owner_kind="fulfillment", owner_id=capacity_reservation_id
            ) if self._port_allocator is not None else None
        )
        reclaim = grant.model_copy(
            update={
                "action": NODE_RECLAIM_ACCESS_ACTION,
                "relay_id": lease.relay_id if lease is not None else None,
                "remote_port": None,
                "relay_addr": None, "relay_port": None,
                "relay_token": None, "relay_grant": None,
                "reclaim_policy": grant.reclaim_policy if bounded else self._reclaim_policy,
                "playbook_path": self._playbook_path,
            }
        )
        return PreparedJob(
            offering_mode=BARE_METAL_OFFERING_MODE,
            action=NODE_RECLAIM_ACCESS_ACTION,
            host_id=host_id,
            executor_target=executor_target,
            parameters=reclaim.model_dump(mode="json"),
        )


__all__ = ["BareMetalFulfillmentPlan"]
