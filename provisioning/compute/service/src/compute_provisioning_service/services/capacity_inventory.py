"""Authoritative physical-resource inventory projection for site capacity APIs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import Host


SessionFactory = Callable[[], Session]


def load_capacity_resource_inventory(
    session_factory: SessionFactory,
) -> list[dict[str, object]]:
    """Return the allowlisted host inventory used by ``site_resource_pools``.

    The provisioning service owns the physical inventory. This adapter keeps
    persistence concerns outside application composition and exposes only the
    stable fields the storefront needs for individual-resource listings.
    """
    with session_factory() as db:
        hosts = db.query(Host).order_by(Host.pool_id.asc(), Host.name.asc()).all()
        return [_project_host(host) for host in hosts]


def _project_host(host: Any) -> dict[str, object]:
    gpu_count = int(host.gpu_count or 0)
    return {
        "resource_id": host.name,
        "pool_id": host.pool_id,
        "resource_type": "compute.gpu",
        "resource_subtype": None,
        "capacity": {"gpu_count": gpu_count},
        "attributes": {
            "vm_host": host.name,
            "public_host": host.public_host or host.kvm_host,
            "gpu_count": gpu_count,
        },
        "enabled": bool(host.enabled),
    }
