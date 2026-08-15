"""VM storefront composition for site inventory and capacity projections."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionCacheView,
    ProjectionIdentity,
)
from market_capacity_publication import remote_site_clients
from market_storefront.services.capacity_client import build_capacity_client

logger = logging.getLogger(__name__)


class _RemoteProjectionClient:
    def __init__(self, remote: Any, family: str) -> None:
        self._remote = remote
        self._family = family

    async def version(self) -> ProjectionIdentity:
        method = getattr(self._remote, f"{self._family}_projection_version")
        data = await method()
        return ProjectionIdentity(int(data["revision"]), str(data["digest"]))

    async def snapshot(self) -> tuple[ProjectionIdentity, list[dict[str, Any]]]:
        method = getattr(self._remote, f"{self._family}_projection")
        data = await method()
        key = (
            "resource_pools" if self._family == "resource_pool" else "capacity_buckets"
        )
        return (
            ProjectionIdentity(int(data["revision"]), str(data["digest"])),
            list(data.get(key) or []),
        )


@dataclass
class SiteProjectionCaches:
    resource_pools: ProjectionCache[list[dict[str, Any]]]
    capacity_buckets: ProjectionCache[list[dict[str, Any]]]


_caches: dict[str, SiteProjectionCaches] = {}


def projection_caches() -> dict[str, SiteProjectionCaches]:
    return dict(_caches)


def projection_status_summary() -> dict[str, dict[str, dict[str, Any]]]:
    """Per-site, per-family projection load state for operator status reporting.

    Reports state and identity only, never the cached payload itself --
    callers needing the projection value use `projection_caches()`
    directly. A missing site or a `not_loaded`/`unavailable`/`invalid`
    state here means the projection has not yet been confirmed; it must
    never be read as authoritative empty capacity.
    """
    return {
        site: {
            "resource_pool": _view_summary(caches.resource_pools.view()),
            "capacity_bucket": _view_summary(caches.capacity_buckets.view()),
        }
        for site, caches in projection_caches().items()
    }


def _view_summary(view: ProjectionCacheView[list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "state": view.state.value,
        "revision": view.identity.revision if view.identity is not None else None,
        "digest": view.identity.digest if view.identity is not None else None,
        "last_error": view.last_error,
        "fetched_at": view.fetched_at.isoformat()
        if view.fetched_at is not None
        else None,
    }


def listing_mode_explanations() -> dict[str, dict[str, str]]:
    """Per-site, per-pool operator-visible explanation for any pool whose
    projected `listing_mode` fell back to the VM domain's structural
    default because the raw tag was present but unrecognized.

    A pool's absence from this mapping means no explanation is owed --
    either the tag is absent (ordinary default, nothing to explain) or it
    resolved to a recognized value -- not that its site hasn't loaded;
    a site whose resource-pool projection hasn't loaded yet simply
    contributes no pools to walk, the same as it contributing none to
    `projection_caches()` more generally. Cheap and independent of full
    publication candidate generation: this only needs each pool's
    projected `policy_tags`, not pricing or availability.
    """
    from domains.vms.listings.listing_mode import resolve_vm_listing_mode

    result: dict[str, dict[str, str]] = {}
    for site, caches in projection_caches().items():
        pools = caches.resource_pools.view().value
        if not pools:
            continue
        site_explanations: dict[str, str] = {}
        for pool in pools:
            pool_id = str(pool.get("resource_pool_id") or "")
            if not pool_id:
                continue
            policy_tags = (pool.get("pool_metadata") or {}).get("policy_tags") or {}
            # Same structural-default rule `_projected_pool_rows` uses
            # (member_count == 1 -> specific_resource, backward
            # compatibility for an untagged pool) -- an explanation is
            # only owed when the raw tag was present but unrecognized,
            # so the actual default value only matters for the message
            # text, not for whether one is produced.
            enabled_member_count = sum(
                1
                for resource in pool.get("resources") or []
                if resource.get("enabled", True)
            )
            structural_default = (
                "specific_resource" if enabled_member_count == 1 else "fungible"
            )
            _, explanation = resolve_vm_listing_mode(
                policy_tags,
                structural_default=structural_default,
            )
            if explanation:
                site_explanations[pool_id] = explanation
        if site_explanations:
            result[site] = site_explanations
    return result


async def load_site_projections(sqlite_client: Any) -> None:
    aggregate = build_capacity_client(lambda: sqlite_client)
    remotes = remote_site_clients(aggregate)
    replacements: dict[str, SiteProjectionCaches] = {}
    for site, remote in remotes.items():
        caches = SiteProjectionCaches(
            resource_pools=ProjectionCache(
                _RemoteProjectionClient(remote, "resource_pool")
            ),
            capacity_buckets=ProjectionCache(
                _RemoteProjectionClient(remote, "capacity_bucket")
            ),
        )
        await asyncio.gather(
            caches.resource_pools.load(), caches.capacity_buckets.load()
        )

        async def _refresh_for_error(
            *, _cache: ProjectionCache[list[dict[str, Any]]] = caches.capacity_buckets
        ) -> None:
            await _cache.refresh_after_topology_error(_cache.view().identity)

        remote.set_topology_error_handler(_refresh_for_error)
        replacements[site] = caches
    _caches.clear()
    _caches.update(replacements)


async def site_projection_poller_loop(sqlite_client: Any) -> None:
    from market_storefront.utils import config

    interval = float(
        getattr(getattr(config.settings, "capacity", None), "poll_interval", 5) or 5
    )
    while True:
        try:
            if not _caches:
                await load_site_projections(sqlite_client)
            else:
                await asyncio.gather(
                    *(
                        cache.poll_once()
                        for site in _caches.values()
                        for cache in (site.resource_pools, site.capacity_buckets)
                    )
                )
        except Exception as exc:
            logger.warning("[PROJECTIONS] refresh failed: %s", exc)
        await asyncio.sleep(interval)


async def refresh_after_topology_error(
    site: str,
    *,
    capacity: bool,
    sqlite_client: Any,
) -> bool:
    caches = _caches.get(site)
    if caches is None:
        await load_site_projections(sqlite_client)
        caches = _caches.get(site)
        if caches is None:
            return False
    cache = caches.capacity_buckets if capacity else caches.resource_pools
    return await cache.refresh_after_topology_error(cache.view().identity)
