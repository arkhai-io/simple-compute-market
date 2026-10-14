"""Bare metal's contribution to the compute family's job-backed fulfillment.

A grant installs the buyer's key for a tenant account on the whole host the
lease sells; the reclaim that undoes it is prepared from the grant job's own
parameters, so it removes exactly the access the grant gave, on the same host,
with the reclaim policy the deployment configures.

The sold unit is one whole host: the job runs against it and acts on it, so its
``host_id`` is both where the job runs and its ``executor_target``. The
machine's ``physical_host_id`` is the declaration's cross-mode identity; it is
checked here against the selected resource and travels in the job's parameters
for the access role, but it names nothing the fulfillment tracks.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    if pool_config:
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

    def __init__(self, *, reclaim_policy: str | None = None) -> None:
        # Validated here, at composition, so a deployment configured with a
        # policy the access role does not implement refuses to start.
        self._reclaim_policy = reclaim_policy_from(reclaim_policy)

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
        # Nothing is acquired while preparing, so validation and acceptance do
        # the same work.
        del allocate, db
        _validate_pool_config(pool_config)
        _require_bare_metal(resource)
        try:
            materialization = BareMetalMaterialization.model_validate(request.payload)
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
        params = BareMetalJobParams(
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
        del capacity_reservation_id
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
        reclaim = grant.model_copy(
            update={
                "action": NODE_RECLAIM_ACCESS_ACTION,
                "reclaim_policy": self._reclaim_policy,
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
