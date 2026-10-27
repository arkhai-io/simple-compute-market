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
attaches the views the composed projections return, naming none of them. A
resource view is given its pool's context -- the pool's provider and resolved
declarations -- which this module reads from the pool rows and interprets not
at all; the problems a projection reports in place of a view are attached
beside the views, as ``publication_view_problems``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from compute_provisioning import InventoryPoolContext, InventoryViews
from market_resource_pools import ResourcePool
from market_resource_pools_contracts.hints import (
    PoolDeclarationError,
    resolve_pool_declarations,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def pool_context(pool: ResourcePool) -> InventoryPoolContext | None:
    """The context a resource view of ``pool``'s members is built with.

    ``None`` when the pool's declarations do not resolve. The service refuses
    to start while a stored pool lacks valid declarations and every write is
    checked, so that is a row written outside the service; its members project
    without views rather than with a context no view could trust.
    """
    try:
        declarations = resolve_pool_declarations(dict(pool.policy_tags or {}))
    except PoolDeclarationError as exc:
        logger.warning(
            "pool %s declarations do not resolve (%s); its resources project "
            "without views",
            pool.id,
            exc,
        )
        return None
    return InventoryPoolContext(
        pool_id=pool.id, provider=pool.provider, declarations=declarations
    )


def load_capacity_resource_inventory(
    capacity_resources: Iterable[Mapping[str, Any]],
    views: InventoryViews,
    session_factory: SessionFactory,
) -> list[dict[str, Any]]:
    """Project every capacity declaration, with the views contributed for it.

    One entry per declaration that records its pool, in declaration order.
    Nothing is read from host records, and no host identifier or address is
    added to an entry. Each pool row is read and resolved once, and every
    declaration of the pool is given that context; a declaration whose pool
    has no row, or a row whose declarations do not resolve, projects with no
    views.

    Every declaration is written naming its pool, so a stored row with none is
    malformed. It is left out and logged rather than projected into any pool:
    reading it as one would sell capacity in a pool nobody placed it in.
    """
    with session_factory() as db:
        contexts = {pool.id: pool_context(pool) for pool in db.query(ResourcePool).all()}
    projected: list[dict[str, Any]] = []
    for resource in capacity_resources:
        if not resource.get("pool_id"):
            logger.warning(
                "capacity declaration %r records no pool and is not projected",
                resource.get("resource_id"),
            )
            continue
        projected.append(_project_declaration(resource, views, contexts))
    return projected


def _project_declaration(
    declaration: Mapping[str, Any],
    views: InventoryViews,
    contexts: Mapping[str, InventoryPoolContext | None],
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
        "pool_id": str(resource["pool_id"]),
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

    pool = contexts.get(projected["pool_id"])
    if pool is None:
        return projected
    built = views.resource_views(resource, pool=pool)
    if built.views:
        projected["publication_views"] = {
            view_id: dict(view) for view_id, view in built.views.items()
        }
    if built.problems:
        projected["publication_view_problems"] = {
            view_id: list(problems) for view_id, problems in built.problems.items()
        }
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
