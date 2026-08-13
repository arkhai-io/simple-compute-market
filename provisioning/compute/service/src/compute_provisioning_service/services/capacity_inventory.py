"""Allowlisted physical-resource inventory for site projection APIs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from bare_metal_provisioning_adapter.runtime import project_bare_metal_resource
from market_resource_pools import ResourcePool
from sqlalchemy.orm import Session
from vm_provisioning_adapter.runtime import project_ansible_pool_defaults

from compute_provisioning_service.db.models import AnsiblePoolConfig, Host

SessionFactory = Callable[[], Session]
BARE_METAL_PUBLICATION_ATTR = "bare_metal_publication"
BARE_METAL_PUBLICATION_VIEW = "bare_metal.v1"
VM_ANSIBLE_POOL_DEFAULTS_VIEW = "vm.ansible_pool_defaults.v1"


def load_capacity_resource_inventory(
    session_factory: SessionFactory,
    *,
    capacity_resources: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return allowlisted host inventory with optional publication views.

    Capacity resources are authoritative for availability and Physical Resource
    identity. Host rows supply only executor inventory needed to correlate the
    configured machine alias; private host connection fields never enter a
    bare-metal publication view.
    """
    resources: dict[str, dict[str, Any]] = {}
    for raw_resource in capacity_resources:
        resource = dict(raw_resource)
        attributes = dict(resource.get("attributes") or {})
        bare_metal = attributes.get(BARE_METAL_PUBLICATION_ATTR)
        keys = {str(resource["resource_id"])}
        if attributes.get("vm_host"):
            keys.add(str(attributes["vm_host"]))
        if isinstance(bare_metal, Mapping) and bare_metal.get("enabled", False):
            machine_id = str(bare_metal.get("machine_id") or "").strip()
            if not machine_id:
                raise ValueError(
                    "enabled bare_metal_publication requires explicit machine_id",
                )
            keys.add(machine_id)
        for key in keys:
            existing = resources.get(key)
            if existing is not None and existing != resource:
                raise ValueError(
                    f"several capacity resources map to host identity {key!r}",
                )
            resources[key] = resource
    with session_factory() as db:
        hosts = db.query(Host).order_by(Host.pool_id.asc(), Host.name.asc()).all()
        return [
            _project_host(host, capacity_resource=resources.get(str(host.name)))
            for host in hosts
        ]


def _project_host(
    host: Any,
    *,
    capacity_resource: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gpu_count = int(host.gpu_count or 0)
    resource = dict(capacity_resource or {})
    capacity = dict(resource.get("capacity") or {"gpu_count": gpu_count})
    # The capacity resource's own attributes come first: this function's contract
    # is that capacity resources are authoritative for Physical Resource identity
    # and host rows supply only executor correlation. Building attributes from the
    # host alone dropped every declared attribute a consumer matches on — region
    # above all, which no host row carries — so a consumer asking for a region it
    # had just published could never match anything.
    attributes: dict[str, Any] = dict(resource.get("attributes") or {})
    attributes.update({
        "vm_host": host.name,
        "public_host": host.public_host or host.kvm_host,
        "gpu_count": gpu_count,
    })
    # Host GPU model is a fallback, not an override: the resource declares what it
    # is offering, and the host only says what hardware is installed.
    if host.gpu_model and not attributes.get("gpu_model"):
        attributes["gpu_model"] = host.gpu_model
    projected: dict[str, Any] = {
        "resource_id": str(resource.get("resource_id") or host.name),
        "pool_id": str(resource.get("pool_id") or host.pool_id),
        "resource_type": resource.get("resource_type") or "compute.gpu",
        "resource_subtype": resource.get("resource_subtype"),
        "capacity": capacity,
        "attributes": attributes,
        "enabled": bool(host.enabled and resource.get("enabled", True)),
    }
    if capacity_resource is not None:
        projected["available"] = dict(resource.get("available") or {})

    publication_view = _bare_metal_publication_view(
        host=host,
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
    host: Any,
    resource: Mapping[str, Any],
    capacity: Mapping[str, Any],
) -> dict[str, Any] | None:
    attributes = dict(resource.get("attributes") or {})
    raw_config = attributes.get(BARE_METAL_PUBLICATION_ATTR)
    if not isinstance(raw_config, Mapping) or not raw_config.get("enabled", False):
        return None

    available = dict(resource.get("available") or {})
    return project_bare_metal_resource({
        "physical_resource_id": str(resource.get("resource_id") or ""),
        "physical_host_id": str(raw_config.get("physical_host_id") or ""),
        "machine_id": str(raw_config.get("machine_id") or ""),
        "available": (
            bool(host.enabled and resource.get("enabled", True))
            and _whole_resource_available(capacity, available)
        ),
        "allocation_mode": str(raw_config.get("allocation_mode") or ""),
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
