"""Allowlisted physical-resource inventory for site projection APIs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from bare_metal_provisioning_adapter.runtime import project_bare_metal_resource
from market_resource_pools import ResourcePool
from vm_provisioning_adapter.runtime import project_ansible_pool_defaults

from compute_provisioning_service.db.models import AnsiblePoolConfig, Host


SessionFactory = Callable[[], Session]
BARE_METAL_PUBLICATION_ATTR = "bare_metal_publication"
BARE_METAL_PUBLICATION_VIEW = "bare_metal.v2"
VM_ANSIBLE_POOL_DEFAULTS_VIEW = "vm.ansible_pool_defaults.v1"


def load_capacity_resource_inventory(
    session_factory: SessionFactory,
    *,
    capacity_resources: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return the declared capacity of each host, with publication views.

    A capacity declaration is the authority for what a host sells: its
    capacity, availability, and attributes all come from the declaration
    whose ``host_id`` names the host. The host supplies only its connection
    fields, and a host no declaration names is not projected, because it has
    nothing declared to report. Private host connection fields never enter a
    bare-metal publication view.
    """
    # A declaration names the host it is delivered through by its own
    # ``host_id``; that field is the only link between the two. Two
    # declarations naming one host would sell the same connection twice, so
    # the projection refuses rather than choosing one.
    resources: dict[str, dict[str, Any]] = {}
    for raw_resource in capacity_resources:
        resource = dict(raw_resource)
        host_id = resource.get("host_id")
        publication = dict(resource.get("attributes") or {}).get(
            BARE_METAL_PUBLICATION_ATTR
        )
        if (
            not host_id
            and isinstance(publication, Mapping)
            and publication.get("enabled", False)
        ):
            # A published bare-metal resource is sold as one specific host;
            # without the host it cannot be correlated or executed.
            raise ValueError(
                "enabled bare_metal_publication requires the resource's host_id",
            )
        if not host_id:
            continue
        existing = resources.get(str(host_id))
        if existing is not None and existing != resource:
            raise ValueError(
                f"several capacity resources name host {host_id!r}",
            )
        resources[str(host_id)] = resource
    with session_factory() as db:
        hosts = db.query(Host).order_by(Host.pool_id.asc(), Host.host_id.asc()).all()
        return [
            _project_host(host, capacity_resource=resources[str(host.host_id)])
            for host in hosts
            if str(host.host_id) in resources
        ]


def _project_host(
    host: Any,
    *,
    capacity_resource: Mapping[str, Any],
) -> dict[str, Any]:
    """One host's projected resource: the declaration, plus connection fields.

    Every declared attribute is projected except the bare-metal publication
    configuration, which is published as its own view. The host's
    ``host_id`` and ``public_host`` are written last, so a declaration cannot
    override how the host is reached.
    """
    resource = dict(capacity_resource)
    capacity = dict(resource.get("capacity") or {})
    attributes: dict[str, Any] = {
        key: value
        for key, value in dict(resource.get("attributes") or {}).items()
        if key != BARE_METAL_PUBLICATION_ATTR
    }
    attributes["host_id"] = host.host_id
    attributes["public_host"] = host.public_host or host.ssh_host
    projected: dict[str, Any] = {
        "resource_id": str(resource["resource_id"]),
        "pool_id": str(resource.get("pool_id") or host.pool_id),
        "resource_type": resource.get("resource_type") or "compute.gpu",
        "resource_subtype": resource.get("resource_subtype"),
        "capacity": capacity,
        "attributes": attributes,
        "enabled": bool(host.enabled and resource.get("enabled", True)),
    }
    # Availability is projected only as the declaration reports it.
    # Consumers trust a present ``available`` as live, so an unreported one
    # must stay absent rather than become an empty map read as zero.
    if resource.get("available") is not None:
        projected["available"] = dict(resource["available"])

    publication_view = _bare_metal_publication_view(
        host=host,
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
    host: Any,
    pool_id: str,
    resource: Mapping[str, Any],
    capacity: Mapping[str, Any],
) -> dict[str, Any] | None:
    attributes = dict(resource.get("attributes") or {})
    raw_config = attributes.get(BARE_METAL_PUBLICATION_ATTR)
    if not isinstance(raw_config, Mapping) or not raw_config.get("enabled", False):
        return None

    available = dict(resource.get("available") or {})
    # The view is a self-contained public projection, so it carries the pool it
    # belongs to rather than leaving a consumer to recover it from the enclosing
    # resource. Omitting it produced a view whose pool_id was null beside a
    # sibling field naming the same pool.
    return project_bare_metal_resource({
        "physical_resource_id": str(resource.get("resource_id") or ""),
        "pool_id": pool_id,
        # Identity and cross-mode accounting come from the declaration itself
        # — its host link and the top-level fields the ledger's cross-mode
        # rule reads — so the view cannot name a different machine than
        # admission accounts for.
        "physical_host_id": str(attributes.get("physical_host_id") or ""),
        "host_id": str(resource.get("host_id") or ""),
        "available": (
            bool(host.enabled and resource.get("enabled", True))
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
