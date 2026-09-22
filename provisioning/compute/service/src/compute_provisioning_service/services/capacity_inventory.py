"""Allowlisted physical-resource inventory for site projection APIs.

The resource-pool projection is built from capacity declarations alone. A
declaration is the authority for a Physical Resource's shape, quantity, pool,
attributes, and enablement, so it projects whether or not it names a host and
whether or not that host is registered. Host records are connection identity,
used where a connection is made: at dispatch, which refuses a host with no
record. Joining them here would add nothing a consumer reads, would leak the
provisioner's connection address to storefronts, and would let a host record
hide a declaration. See
openspec/specs/site-capacity/spec.md#requirement-the-resource-pool-projection-is-built-from-capacity-declarations.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from bare_metal_provisioning_adapter.runtime import project_bare_metal_resource
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from vm_provisioning_adapter.runtime import project_ansible_pool_defaults

from compute_provisioning_service.db.models import AnsiblePoolConfig


SessionFactory = Callable[[], Session]
BARE_METAL_PUBLICATION_ATTR = "bare_metal_publication"
BARE_METAL_PUBLICATION_VIEW = "bare_metal.v2"
VM_ANSIBLE_POOL_DEFAULTS_VIEW = "vm.ansible_pool_defaults.v1"


def load_capacity_resource_inventory(
    capacity_resources: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Project every capacity declaration, with its publication views.

    One entry per declaration, in declaration order. Nothing is read from host
    records, and no host identifier or address is added to an entry.
    """
    return [_project_declaration(resource) for resource in capacity_resources]


def _project_declaration(declaration: Mapping[str, Any]) -> dict[str, Any]:
    """One declaration's projected resource.

    Every declared attribute is projected except the bare-metal publication
    configuration, which is published as its own view.
    """
    resource = dict(declaration)
    capacity = dict(resource.get("capacity") or {})
    attributes: dict[str, Any] = {
        key: value
        for key, value in dict(resource.get("attributes") or {}).items()
        if key != BARE_METAL_PUBLICATION_ATTR
    }
    projected: dict[str, Any] = {
        "resource_id": str(resource["resource_id"]),
        # A declaration stored before pools were recorded belongs to the
        # default pool.
        "pool_id": str(resource.get("pool_id") or DEFAULT_POOL_ID),
        "resource_type": resource.get("resource_type") or "compute.gpu",
        "resource_subtype": resource.get("resource_subtype"),
        "capacity": capacity,
        "attributes": attributes,
        "enabled": bool(resource.get("enabled", True)),
    }
    # Availability is projected only as the declaration reports it.
    # Consumers trust a present ``available`` as live, so an unreported one
    # must stay absent rather than become an empty map read as zero.
    if resource.get("available") is not None:
        projected["available"] = dict(resource["available"])

    publication_view = _bare_metal_publication_view(
        pool_id=projected["pool_id"],
        resource=resource,
        capacity=capacity,
    )
    if publication_view is not None:
        projected["publication_views"] = {
            BARE_METAL_PUBLICATION_VIEW: publication_view,
        }
    return projected


def _bare_metal_publication_view(
    *,
    pool_id: str,
    resource: Mapping[str, Any],
    capacity: Mapping[str, Any],
) -> dict[str, Any] | None:
    attributes = dict(resource.get("attributes") or {})
    raw_config = attributes.get(BARE_METAL_PUBLICATION_ATTR)
    if not isinstance(raw_config, Mapping) or not raw_config.get("enabled", False):
        return None
    host_id = resource.get("host_id")
    if not host_id:
        # The view sells one specific host. A declaration naming none has
        # nothing to sell as one, so it projects without the view; failing
        # instead would take every other declaration at the site out of the
        # projection with it.
        return None

    available = dict(resource.get("available") or {})
    # The view is a self-contained public projection, so it carries the pool it
    # belongs to rather than leaving a consumer to recover it from the enclosing
    # resource.
    return project_bare_metal_resource({
        "physical_resource_id": str(resource.get("resource_id") or ""),
        "pool_id": pool_id,
        # Identity and cross-mode accounting come from the declaration itself
        # — its host field and the attributes the ledger's cross-mode rule
        # reads — so the view cannot name a different machine than admission
        # accounts for.
        "physical_host_id": str(attributes.get("physical_host_id") or ""),
        "host_id": str(host_id),
        "available": (
            bool(resource.get("enabled", True))
            and _whole_resource_available(capacity, available)
        ),
        "allocation_mode": str(attributes.get("allocation_mode") or ""),
        "access_methods": list(raw_config.get("access_methods") or []),
        "capacity": dict(capacity),
        "capabilities": dict(raw_config.get("capabilities") or {}),
    })


def _whole_resource_available(
    capacity: Mapping[str, Any],
    available: Mapping[str, Any],
) -> bool:
    """Return whether every positive capacity dimension remains available."""
    compared = False
    for key, raw_total in capacity.items():
        try:
            total = Decimal(str(raw_total))
            remaining = Decimal(str(available.get(key, 0)))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not total.is_finite() or not remaining.is_finite() or total < 0:
            return False
        if total > 0:
            compared = True
            if remaining < total:
                return False
    return compared


def load_capacity_pool_metadata(
    session_factory: SessionFactory,
) -> dict[str, dict[str, Any]]:
    """Return allowlisted per-pool metadata for the resource-pool projection.

    Only `ResourcePool`'s own columns and the Ansible provider's VM size
    defaults are projected. `provider_config` (which may carry
    credentials) is never read here -- a future provider-config field
    needing projection must be added to this allowlist explicitly, not by
    widening what this function reads.

    The Ansible view is additionally gated on `pool.provider == "ansible"`,
    not merely on an `ansible_pool_configs` row existing. Pool mutation
    already deletes the old provider's config row when a pool's provider
    changes (`ResourcePoolService`), so a stale row shouldn't normally
    exist -- but this is a zero-cost structural guarantee that the
    `vm.ansible_pool_defaults.v1` view can never be published for a pool
    whose declared `mechanism` says otherwise.
    """
    with session_factory() as db:
        pools = db.query(ResourcePool).all()
        ansible_configs = {
            row.pool_id: row for row in db.query(AnsiblePoolConfig).all()
        }
        metadata: dict[str, dict[str, Any]] = {}
        for pool in pools:
            projected: dict[str, Any] = {
                "label": pool.label,
                "enabled": bool(pool.enabled),
                "mechanism": pool.provider,
                "policy_tags": dict(pool.policy_tags or {}),
            }
            config = ansible_configs.get(pool.id)
            if pool.provider == "ansible" and config is not None:
                defaults = project_ansible_pool_defaults({
                    "default_vm_ram": config.default_vm_ram,
                    "default_vm_vcpus": config.default_vm_vcpus,
                    "default_vm_disk_size": config.default_vm_disk_size,
                })
                if defaults:
                    projected["pool_views"] = {VM_ANSIBLE_POOL_DEFAULTS_VIEW: defaults}
            metadata[pool.id] = projected
        return metadata
