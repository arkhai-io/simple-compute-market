"""VM storefront composition for site inventory and capacity projections."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from core_storefront.site_projections import ProjectionCache, ProjectionIdentity
from market_storefront.services.capacity_client import build_capacity_client, remote_site_clients
from market_storefront.utils.sqlite_client import get_sqlite_client

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
        key = "resource_pools" if self._family == "resource_pool" else "capacity_buckets"
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


async def load_site_projections() -> None:
    aggregate = build_capacity_client(lambda: get_sqlite_client())
    remotes = remote_site_clients(aggregate)
    replacements: dict[str, SiteProjectionCaches] = {}
    for site, remote in remotes.items():
        caches = SiteProjectionCaches(
            resource_pools=ProjectionCache(_RemoteProjectionClient(remote, "resource_pool")),
            capacity_buckets=ProjectionCache(_RemoteProjectionClient(remote, "capacity_bucket")),
        )
        await asyncio.gather(caches.resource_pools.load(), caches.capacity_buckets.load())

        async def _refresh_for_error(
            *, _cache: ProjectionCache[list[dict[str, Any]]] = caches.capacity_buckets
        ) -> None:
            await _cache.refresh_after_topology_error(_cache.view().identity)

        remote.set_topology_error_handler(_refresh_for_error)
        replacements[site] = caches
    _caches.clear()
    _caches.update(replacements)


async def site_projection_poller_loop() -> None:
    from market_storefront.utils import config

    interval = float(getattr(getattr(config.settings, "capacity", None), "poll_interval", 5) or 5)
    while True:
        try:
            if not _caches:
                await load_site_projections()
            else:
                await asyncio.gather(*(
                    cache.poll_once()
                    for site in _caches.values()
                    for cache in (site.resource_pools, site.capacity_buckets)
                ))
        except Exception as exc:
            logger.warning("[PROJECTIONS] refresh failed: %s", exc)
        await asyncio.sleep(interval)


async def refresh_after_topology_error(site: str, *, capacity: bool) -> bool:
    caches = _caches.get(site)
    if caches is None:
        await load_site_projections()
        caches = _caches.get(site)
        if caches is None:
            return False
    cache = caches.capacity_buckets if capacity else caches.resource_pools
    return await cache.refresh_after_topology_error(cache.view().identity)
