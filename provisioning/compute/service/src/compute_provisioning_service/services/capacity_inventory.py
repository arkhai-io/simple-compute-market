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

Every domain view is contributed: this module projects what is neutral and
attaches the views the composed projections return, naming none of them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from compute_provisioning import InventoryViews
from market_resource_pools import DEFAULT_POOL_ID, ResourcePool
from sqlalchemy.orm import Session


SessionFactory = Callable[[], Session]


def load_capacity_resource_inventory(
    capacity_resources: Iterable[Mapping[str, Any]],
    views: InventoryViews,
) -> list[dict[str, Any]]:
    """Project every capacity declaration, with the views contributed for it.

    One entry per declaration, in declaration order. Nothing is read from host
    records, and no host identifier or address is added to an entry.
    """
    return [_project_declaration(resource, views) for resource in capacity_resources]


def _project_declaration(
    declaration: Mapping[str, Any], views: InventoryViews
) -> dict[str, Any]:
    """One declaration's projected resource.

    Every declared attribute is projected except those a contributed view
    publishes from, which appear only through that view.
    """
    resource = dict(declaration)
    consumed = views.consumed_attributes
    attributes: dict[str, Any] = {
        key: value
        for key, value in dict(resource.get("attributes") or {}).items()
        if key not in consumed
    }
    projected: dict[str, Any] = {
        "resource_id": str(resource["resource_id"]),
        # A declaration stored before pools were recorded belongs to the
        # default pool.
        "pool_id": str(resource.get("pool_id") or DEFAULT_POOL_ID),
        "resource_type": resource.get("resource_type") or "compute.gpu",
        "resource_subtype": resource.get("resource_subtype"),
        "capacity": dict(resource.get("capacity") or {}),
        "attributes": attributes,
        "enabled": bool(resource.get("enabled", True)),
    }
    # Availability is projected only as the declaration reports it.
    # Consumers trust a present ``available`` as live, so an unreported one
    # must stay absent rather than become an empty map read as zero.
    if resource.get("available") is not None:
        projected["available"] = dict(resource["available"])

    publication_views = views.resource_views(resource, pool_id=projected["pool_id"])
    if publication_views:
        projected["publication_views"] = publication_views
    return projected


def load_capacity_pool_metadata(
    session_factory: SessionFactory,
    views: InventoryViews,
) -> dict[str, dict[str, Any]]:
    """Return allowlisted per-pool metadata for the resource-pool projection.

    Only `ResourcePool`'s own columns are projected, with the views the
    composed projections contribute for each pool. `provider_config` (which
    may carry credentials) is never read here; a projection reads what its
    view needs from its own provider's configuration, in this session.
    """
    with session_factory() as db:
        metadata: dict[str, dict[str, Any]] = {}
        for pool in db.query(ResourcePool).all():
            projected: dict[str, Any] = {
                "label": pool.label,
                "enabled": bool(pool.enabled),
                "mechanism": pool.provider,
                "policy_tags": dict(pool.policy_tags or {}),
            }
            pool_views = views.pool_views(db, pool_id=pool.id, provider=pool.provider)
            if pool_views:
                projected["pool_views"] = pool_views
            metadata[pool.id] = projected
        return metadata
