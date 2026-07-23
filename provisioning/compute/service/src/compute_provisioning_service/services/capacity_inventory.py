"""Allowlisted physical-resource inventory for site projection APIs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import Host


SessionFactory = Callable[[], Session]
BARE_METAL_PUBLICATION_ATTR = "bare_metal_publication"
BARE_METAL_PUBLICATION_VIEW = "bare_metal.v1"


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
    projected: dict[str, Any] = {
        "resource_id": str(resource.get("resource_id") or host.name),
        "pool_id": str(resource.get("pool_id") or host.pool_id),
        "resource_type": resource.get("resource_type") or "compute.gpu",
        "resource_subtype": resource.get("resource_subtype"),
        "capacity": capacity,
        "attributes": {
            "vm_host": host.name,
            "public_host": host.public_host or host.kvm_host,
            "gpu_count": gpu_count,
        },
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

    # Loaded lazily so VM-only installations do not acquire the bare-metal
    # domain dependency. Enabling this view requires the corresponding adapter
    # bundle, which installs the domain contract.
    from arkhai_bare_metal import BareMetalResourceProjection

    available = dict(resource.get("available") or {})
    view = BareMetalResourceProjection.model_validate({
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
    return view.model_dump(mode="json")


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
