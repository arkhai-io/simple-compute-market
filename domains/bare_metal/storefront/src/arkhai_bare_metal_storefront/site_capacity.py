"""Schema-opaque multi-site capacity and projection composition."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping

from arkhai_bare_metal.projections import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
)
from core_storefront.aggregation import AggregateCapacityClient, PlacementPolicy
from core_storefront.capacity_remote import RemoteCapacityClient
from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionIdentity,
    ProjectionState,
)


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
            "resource_pools"
            if self._family == "resource_pool"
            else "capacity_buckets"
        )
        return (
            ProjectionIdentity(int(data["revision"]), str(data["digest"])),
            list(data.get(key) or []),
        )


@dataclass(frozen=True)
class SiteProjectionCaches:
    resource_pools: ProjectionCache[list[dict[str, Any]]]
    capacity_buckets: ProjectionCache[list[dict[str, Any]]]


class BareMetalSiteCapacity:
    """One storefront's trusted clients and retained per-site generations."""

    def __init__(
        self,
        remotes: Mapping[str, Any],
        *,
        placement: PlacementPolicy | None = None,
    ) -> None:
        if not remotes:
            raise ValueError("at least one trusted site client is required")
        self._remotes = dict(remotes)
        self._aggregate = AggregateCapacityClient(
            self._remotes,
            placement=placement,
        )
        self._caches: dict[str, SiteProjectionCaches] = {}
        self._poll_task: asyncio.Task[None] | None = None

    @classmethod
    def from_bindings(cls, bindings) -> "BareMetalSiteCapacity":
        return cls({
            binding.site_id: RemoteCapacityClient(
                binding.authority_url,
                binding.admin_key,
            )
            for binding in bindings.bindings
        })

    @property
    def aggregate(self) -> AggregateCapacityClient:
        return self._aggregate

    def client_for_site(self, site_id: str) -> Any:
        return self._remotes[site_id]

    def cache_views(self) -> dict[str, dict[str, Any]]:
        return {
            site_id: {
                "resource_pools": caches.resource_pools.view(),
                "capacity_buckets": caches.capacity_buckets.view(),
            }
            for site_id, caches in self._caches.items()
        }

    async def load(self) -> None:
        replacements = {
            site_id: SiteProjectionCaches(
                resource_pools=ProjectionCache(
                    _RemoteProjectionClient(remote, "resource_pool"),
                ),
                capacity_buckets=ProjectionCache(
                    _RemoteProjectionClient(remote, "capacity_bucket"),
                ),
            )
            for site_id, remote in self._remotes.items()
        }
        await asyncio.gather(*(
            cache.load()
            for caches in replacements.values()
            for cache in (caches.resource_pools, caches.capacity_buckets)
        ))
        self._caches = replacements
        for site_id, remote in self._remotes.items():
            setter = getattr(remote, "set_topology_error_handler", None)
            if setter is None:
                continue
            cache = self._caches[site_id].capacity_buckets

            async def _refresh(
                *,
                _cache: ProjectionCache[list[dict[str, Any]]] = cache,
            ) -> None:
                await _cache.refresh_after_topology_error(
                    _cache.view().identity,
                )

            setter(_refresh)

    async def poll_once(self) -> None:
        if not self._caches:
            await self.load()
            return
        await asyncio.gather(*(
            cache.poll_once()
            for caches in self._caches.values()
            for cache in (caches.resource_pools, caches.capacity_buckets)
        ))

    async def start(self, interval: float) -> None:
        await self.load()
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(
                self.poll_forever(interval),
                name="bare_metal_site_projection_poller",
            )

    async def close(self) -> None:
        task = self._poll_task
        self._poll_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def poll_forever(self, interval: float) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(interval)

    async def reserve(self, **kwargs: Any) -> dict[str, Any] | None:
        return await self._aggregate.reserve(**kwargs)

    def bare_metal_projections(self) -> tuple[TrustedBareMetalProjection, ...]:
        """Interpret retained inventory views with configured site provenance."""
        projections: list[TrustedBareMetalProjection] = []
        for site_id, caches in self._caches.items():
            view = caches.resource_pools.view()
            if view.identity is None or view.value is None:
                continue
            resources: list[BareMetalResourceProjection] = []
            for row in view.value:
                publication_views = row.get("publication_views")
                if not isinstance(publication_views, dict):
                    continue
                payload = publication_views.get("bare_metal.v1")
                if payload is not None:
                    resources.append(
                        BareMetalResourceProjection.model_validate(payload),
                    )
            projections.append(TrustedBareMetalProjection(
                site_id=site_id,
                revision=view.identity.revision,
                digest=view.identity.digest,
                complete=True,
                stale=view.state == ProjectionState.stale,
                resources=resources,
            ))
        return tuple(projections)

    def projection_health(self) -> str:
        if not self._caches:
            return "unavailable"
        states = [
            cache.view().state
            for caches in self._caches.values()
            for cache in (caches.resource_pools, caches.capacity_buckets)
        ]
        if all(state == ProjectionState.loaded for state in states):
            return "ok"
        if any(state == ProjectionState.stale for state in states):
            return "stale"
        return "unavailable"
