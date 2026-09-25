"""Resolve what a VM listing source's site declares about it, read live.

Publication records a listing's backing on its durable binding when the listing
is created, taking it from the declaration the source's site projects at that
moment. The projected declaration itself is never stored: it is read from the
current projection each time it is needed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from market_resource_pools import SiteDeclarations, read_site_declarations
from market_storefront.services.site_projection_cache import projection_caches
from market_storefront.utils.config import settings


class ListingSourceUnavailable(ValueError):
    """The source's site does not currently declare it as publishable."""


def _projection_enabled() -> bool:
    return bool(
        getattr(
            getattr(settings, "capacity", None),
            "use_site_projection_for_listings",
            False,
        )
    )


def _site_pools(site_id: str) -> Sequence[Mapping[str, Any]] | None:
    caches = projection_caches().get(site_id)
    if caches is None:
        return None
    return caches.resource_pools.view().value


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
    *,
    site_id: str,
    pool_id: str | None,
    resource_id: str | None,
    offering_mode: str,
) -> str:
    """The backing a listing from this source binds with, or refuse.

    Local-table sources can express only capacity-backed supply. A projected
    source must be a pool its site currently declares enabled and advertisable
    for ``offering_mode``, under that site generation's declaration rule;
    anything else is refused rather than classified.
    """
    if not _projection_enabled():
        return "backed"
    pools = _site_pools(site_id)
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
    return declaration.capacity_backing


def current_source_backing(
    *,
    site_id: str,
    pool_id: str | None,
    resource_id: str | None,
) -> str | None:
    """The backing the source's site declares now, or ``None`` if unreadable."""
    if not _projection_enabled():
        return "backed"
    pools = _site_pools(site_id)
    if pools is None:
        return None
    resolved_pool_id = _pool_for_source(
        pools, pool_id=pool_id, resource_id=resource_id
    )
    if resolved_pool_id is None:
        return None
    declaration = read_site_declarations(pools).resolved.get(resolved_pool_id)
    return declaration.capacity_backing if declaration is not None else None


__all__ = [
    "ListingSourceUnavailable",
    "current_source_backing",
    "resolve_source_backing",
]
