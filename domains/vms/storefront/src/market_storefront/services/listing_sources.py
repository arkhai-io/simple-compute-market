"""Resolve what a VM listing source's site declares about it, read live.

Publication records a listing's backing on its durable binding when the listing
is created, taking it from the declaration the source's site projects at that
moment. The projected declaration itself is never stored: it is read from the
current projection each time it is needed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from market_capacity_publication import RESOURCE_POOL, SiteProjectionState
from market_resource_pools import SiteDeclarations, read_site_declarations
from market_resource_pools_contracts.backing import CapacityBacking


class ListingSourceUnavailable(ValueError):
    """The source's site does not currently declare it as publishable."""


def _site_pools(
    site_projections: SiteProjectionState, site_id: str
) -> Sequence[Mapping[str, Any]] | None:
    return site_projections.values(RESOURCE_POOL).get(site_id)


def _pool_for_source(
    pools: Sequence[Mapping[str, Any]],
    *,
    pool_id: str | None,
    resource_id: str | None,
) -> str | None:
    for pool in pools:
        candidate = str(pool.get("pool_id") or "")
        if pool_id is not None:
            if candidate == pool_id:
                return candidate
            continue
        for resource in pool.get("resources") or []:
            if str(resource.get("physical_resource_id") or "") == resource_id:
                return candidate
    return None


def resolve_source_backing(
    site_projections: SiteProjectionState,
    *,
    site_id: str,
    pool_id: str | None,
    resource_id: str | None,
    offering_mode: str,
) -> CapacityBacking:
    """The backing a listing from this source binds with, or refuse.

    The source must be a pool its site currently declares enabled and
    advertisable for ``offering_mode``, under that site generation's declaration
    rule; anything else is refused rather than classified.
    """
    pools = _site_pools(site_projections, site_id)
    if pools is None:
        raise ListingSourceUnavailable(
            f"site {site_id!r} has no loaded resource-pool projection"
        )
    resolved_pool_id = _pool_for_source(
        pools, pool_id=pool_id, resource_id=resource_id
    )
    if resolved_pool_id is None:
        raise ListingSourceUnavailable(
            f"site {site_id!r} projects no pool for this listing source"
        )
    declarations: SiteDeclarations = read_site_declarations(pools)
    if resolved_pool_id in declarations.unresolvable:
        raise ListingSourceUnavailable(
            f"pool {resolved_pool_id!r} at site {site_id!r} is unresolvable: "
            + ", ".join(declarations.unresolvable[resolved_pool_id])
        )
    declaration = declarations.resolved[resolved_pool_id]
    if not declaration.enabled:
        raise ListingSourceUnavailable(
            f"pool {resolved_pool_id!r} at site {site_id!r} is disabled"
        )
    if not declaration.advertises(offering_mode):
        raise ListingSourceUnavailable(
            f"pool {resolved_pool_id!r} at site {site_id!r} does not declare "
            f"{offering_mode!r} advertisable"
        )
    return declaration.backing


__all__ = [
    "ListingSourceUnavailable",
    "resolve_source_backing",
]
