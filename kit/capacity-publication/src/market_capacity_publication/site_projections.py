"""Per-site projection state: both projection families of every configured site.

A storefront that derives listings from site projections builds one
``SiteProjectionState`` per process over its aggregate capacity client and
passes it to every consumer, so publication, source checks, override status,
and system status all read one held generation per site and family. The state
is domain-neutral: it holds whatever generation a site serves, and a domain's
acceptance rules for a generation apply where that domain reads it.

Each refresh path belongs to one category, which decides whether it wakes
publication:

- **poll and notify** -- the poller's cycle, an operator-invoked poll, and the
  drift check a topology-sensitive error triggers: ``on_resource_pool_change``
  runs when a site's resource-pool identity changed;
- **refresh and reconcile** -- ``refresh_site``, for an operation that has just
  changed a site and reconciles inline: it never wakes publication, because its
  caller reconciles what it changed itself.

A failed operation in any category keeps the site's last generation as
``stale`` with its error and does not advance its confirmation. Operations on
one site's family never overlap (see ``ProjectionCache``), so a failed
operation never replaces a confirmation that completed after it began.
See openspec/specs/storefront-publication/spec.md, "Projection-backed listing
candidate derivation".
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from core_storefront.aggregation import AggregateCapacityClient
from core_storefront.models.system_models import ProjectionFamilyStatus
from core_storefront.site_projections import (
    ProjectionCache,
    ProjectionCacheView,
    ProjectionIdentity,
    ProjectionState,
)

from .capacity import CapacityBindingError, CapacityConfigurationError

RESOURCE_POOL = "resource_pool"
CAPACITY_BUCKET = "capacity_bucket"
FAMILIES: tuple[str, ...] = (RESOURCE_POOL, CAPACITY_BUCKET)

# The key each family's snapshot carries its rows under.
_ROWS_KEY = {RESOURCE_POOL: "resource_pools", CAPACITY_BUCKET: "capacity_buckets"}

Rows = list[dict[str, Any]]


class _RemoteProjectionClient:
    """One projection family of one site, read through that site's client."""

    def __init__(self, remote: Any, family: str) -> None:
        self._remote = remote
        self._family = family

    async def version(self) -> ProjectionIdentity:
        method = getattr(self._remote, f"{self._family}_projection_version")
        data = await method()
        return ProjectionIdentity(int(data["revision"]), str(data["digest"]))

    async def snapshot(self) -> tuple[ProjectionIdentity, Rows]:
        method = getattr(self._remote, f"{self._family}_projection")
        data = await method()
        return (
            ProjectionIdentity(int(data["revision"]), str(data["digest"])),
            list(data.get(_ROWS_KEY[self._family]) or []),
        )


def freshly_confirmed(
    view: ProjectionCacheView[Any], *, now: datetime, window_seconds: float
) -> bool:
    """Whether a held generation may confirm a listing-source check.

    Only a ``loaded`` generation whose last confirmation is no older than the
    window qualifies. A cache becomes ``stale`` only when a poll fails, so a
    generation no poll has reached -- the loops held while trading continues, or
    a poller that has stopped -- stays ``loaded`` indefinitely; the window is
    what bounds how far a source check can lag its site. Publication reads held
    generations without this rule, because holding listings through an outage
    is its job.
    """

    if view.state is not ProjectionState.loaded or view.fetched_at is None:
        return False
    return now - view.fetched_at <= timedelta(seconds=window_seconds)


class SiteProjectionState:
    """The resource-pool and capacity-bucket projections of every configured site.

    Built once per storefront process over the aggregate capacity client its
    composition root owns, and never replaced: every refresh updates a site's
    caches in place. ``on_resource_pool_change`` is the publication wake.
    """

    def __init__(
        self,
        client: AggregateCapacityClient,
        *,
        on_resource_pool_change: Callable[[], None],
    ) -> None:
        if not isinstance(client, AggregateCapacityClient):
            # Only an aggregate names its sites; anything else would leave the
            # state to guess which sites exist.
            raise CapacityConfigurationError(
                "site projection state requires an aggregate capacity client"
            )
        self._on_resource_pool_change = on_resource_pool_change
        self._caches: dict[str, dict[str, ProjectionCache[Rows]]] = {}
        for site_id in client.site_names:
            remote = client.site(site_id)
            self._caches[site_id] = {
                family: ProjectionCache(_RemoteProjectionClient(remote, family))
                for family in FAMILIES
            }
            remote.set_topology_error_handler(self._drift_check_for(site_id))

    def values(self, family: str) -> Mapping[str, Rows]:
        """Site -> rows for every site holding a generation, stale included.

        A site holding none is absent; a loaded empty site maps to ``[]``.
        """

        _require_family(family)
        held: dict[str, Rows] = {}
        for site_id, caches in self._caches.items():
            value = caches[family].view().value
            if value is not None:
                held[site_id] = list(value)
        return held

    def view(self, site_id: str, family: str) -> ProjectionCacheView[Rows]:
        """State, identity, value, last error, and last confirmation of one family."""

        return self._site(site_id)[_require_family(family)].view()

    def status(self) -> dict[str, dict[str, ProjectionFamilyStatus]]:
        """Per-site, per-family load state, never the held rows themselves."""

        return {
            site_id: {
                family: _family_status(cache.view()) for family, cache in caches.items()
            }
            for site_id, caches in self._caches.items()
        }

    async def poll_once(self) -> None:
        """The poller's cycle: poll every family of every site, the first load included."""

        before = self._resource_pool_identities()
        await asyncio.gather(
            *(cache.poll_once() for caches in self._caches.values() for cache in caches.values())
        )
        self._notify_if_changed(before)

    async def refresh_site(
        self, site_id: str, *, families: Iterable[str] | None = None
    ) -> None:
        """Fetch one site's families in place for a caller reconciling inline.

        Never wakes publication and never raises for a failed fetch: the cache
        records the failure and keeps its last generation.
        """

        caches = self._site(site_id)
        selected = FAMILIES if families is None else tuple(
            dict.fromkeys(_require_family(family) for family in families)
        )
        await asyncio.gather(*(caches[family].refresh(force=True) for family in selected))

    def _site(self, site_id: str) -> dict[str, ProjectionCache[Rows]]:
        caches = self._caches.get(site_id)
        if caches is None:
            raise CapacityBindingError(f"unknown capacity site_id {site_id!r}")
        return caches

    def _drift_check_for(self, site_id: str) -> Callable[[], Awaitable[None]]:
        async def _drift_check() -> None:
            # One version check per family, shared with any operation already
            # running on it. The refused request itself is never retried here.
            caches = self._caches[site_id]
            before = self._resource_pool_identities()
            await asyncio.gather(
                *(
                    cache.refresh_after_topology_error(cache.view().identity)
                    for cache in caches.values()
                )
            )
            self._notify_if_changed(before)

        return _drift_check

    def _resource_pool_identities(self) -> dict[str, ProjectionIdentity | None]:
        return {
            site_id: caches[RESOURCE_POOL].view().identity
            for site_id, caches in self._caches.items()
        }

    def _notify_if_changed(self, before: Mapping[str, ProjectionIdentity | None]) -> None:
        if self._resource_pool_identities() != before:
            # A pool-level change a site declares -- a tag edit, a disabled
            # pool -- emits no capacity event, so publication is woken here
            # rather than waiting out its interval.
            self._on_resource_pool_change()


def _require_family(family: str) -> str:
    if family not in FAMILIES:
        raise ValueError(
            f"unknown projection family {family!r}; expected one of {', '.join(FAMILIES)}"
        )
    return family


def _family_status(view: ProjectionCacheView[Rows]) -> ProjectionFamilyStatus:
    return ProjectionFamilyStatus(
        state=view.state.value,
        revision=view.identity.revision if view.identity is not None else None,
        digest=view.identity.digest if view.identity is not None else None,
        last_error=view.last_error,
        fetched_at=view.fetched_at.isoformat() if view.fetched_at is not None else None,
    )
