"""Storefront pool overrides: writes checked against the site, and their status.

A write is checked against its site's resource-pool projection, fetched live
through the site's authenticated client rather than read from the storefront's
cache, so neither a stale cache nor a stale refusal decides it. Derivation reads
stored overrides itself; this service stores them, reports what each would do,
and prompts publication to act on a change.

The service knows no market: the contribution registered for a record's offering
mode judges its vocabulary and its shapes.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any

from market_site_client import SiteCapacityAuthenticationError, SiteCapacityClientError

from market_pool_overrides.contribution import PoolOverrideContribution
from market_pool_overrides.records import PoolOverrideAddress, PoolOverrideRecord
from market_pool_overrides.store import SQLitePoolOverrideStore

logger = logging.getLogger(__name__)

#: Every stored override reports exactly one of these.
OVERRIDE_INACTIVE = "inactive"
OVERRIDE_SITE_UNCONFIGURED = "site_unconfigured"
OVERRIDE_UNKNOWN = "unknown"
OVERRIDE_ORPHANED = "orphaned"
OVERRIDE_APPLIED = "applied"

#: The source listings derive from: ``None`` when they derive from local tables,
#: otherwise each site whose projection is known mapped to its pools.
ProjectionSource = Callable[[], Mapping[str, list[Mapping[str, Any]]] | None]


class PoolOverrideRefused(Exception):
    """A write was refused; ``status_code`` is the HTTP status to answer with."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def override_state(
    *,
    site_id: str,
    pool_id: str,
    site_ids: Collection[str],
    projection: Mapping[str, list[Mapping[str, Any]]] | None,
) -> str:
    """The one state an override is in, judged against ``projection``.

    A configured site missing from ``projection`` is unknown rather than empty,
    so its override is never called orphaned on the strength of an answer the
    storefront does not have.
    """
    if projection is None:
        return OVERRIDE_INACTIVE
    if site_id not in site_ids:
        return OVERRIDE_SITE_UNCONFIGURED
    pools = projection.get(site_id)
    if pools is None:
        return OVERRIDE_UNKNOWN
    if any(str(pool.get("pool_id") or "") == pool_id for pool in pools):
        return OVERRIDE_APPLIED
    return OVERRIDE_ORPHANED


class PoolOverrideService:
    """Store, read, and delete overrides, and report their status.

    Every collaborator is injected by the storefront's composition root: the
    store; the configured sites and a factory for each one's signed client; the
    contribution per offering mode; the market-neutral settlement-clause
    compiler; the source listings derive from; and the two effects a write has
    on publication.
    """

    def __init__(
        self,
        *,
        store: SQLitePoolOverrideStore,
        site_ids: Callable[[], Collection[str]],
        site_client: Callable[[str], Any],
        contributions: Mapping[str, PoolOverrideContribution],
        compile_clauses: Callable[[list[dict[str, Any]]], Any],
        projection_source: ProjectionSource,
        refresh_site: Callable[[str], Awaitable[None]],
        wake_publication: Callable[[], None],
    ) -> None:
        self._store = store
        self._site_ids = site_ids
        self._site_client = site_client
        self._contributions = dict(contributions)
        self._compile_clauses = compile_clauses
        self._projection_source = projection_source
        self._refresh_site = refresh_site
        self._wake_publication = wake_publication

    async def replace(self, record: PoolOverrideRecord) -> dict[str, Any]:
        """Check ``record`` against its site's live projection, then store it.

        Refuses, in order and before anything is stored: an unconfigured site, a
        mode no market serves, vocabulary its market cannot read, or clauses
        that do not compile (422, with no site call); a site that cannot be
        reached or whose answer is unusable (503, retryable); a pool the live
        projection does not hold (404). A shape no member is feasible for is
        reported, not refused.
        """
        if record.site_id not in self._site_ids():
            raise PoolOverrideRefused(
                422, f"site {record.site_id!r} is not a configured capacity site"
            )
        contribution = self._contributions.get(record.offering_mode)
        if contribution is None:
            raise PoolOverrideRefused(
                422, f"no market serves offering mode {record.offering_mode!r}"
            )
        problems = list(contribution.vocabulary_problems(record))
        if problems:
            raise PoolOverrideRefused(422, "; ".join(problems))
        if record.settlements is not None:
            try:
                self._compile_clauses(record.settlements)
            except ValueError as exc:
                raise PoolOverrideRefused(422, f"settlements do not compile: {exc}") from exc

        revision, digest, site_pools = await self._live_projection(record.site_id)
        if not any(
            str(pool.get("pool_id") or "") == record.pool_id for pool in site_pools
        ):
            raise PoolOverrideRefused(
                404,
                f"site {record.site_id!r} does not project pool {record.pool_id!r} "
                f"(projection revision {revision})",
            )

        feasibility = contribution.judge_shapes(site_pools, record=record)
        stored = await self._store.replace(record)
        await self._after_write(record.site_id)
        return {
            "override": stored,
            "feasibility": [entry.model_dump() for entry in feasibility],
            "projection": {"revision": revision, "digest": digest},
        }

    async def _live_projection(
        self, site_id: str
    ) -> tuple[int, str, list[Mapping[str, Any]]]:
        """Fetch ``site_id``'s resource-pool projection through its signed client.

        Every failure is retryable and names the site and the kind of failure,
        so an operator can tell an unreachable site from an untrusted or unusable
        answer, and either from an unknown pool.
        """
        try:
            answer = await self._site_client(site_id).resource_pool_projection()
        except SiteCapacityAuthenticationError as exc:
            raise PoolOverrideRefused(
                503, f"site {site_id!r} answered, but its answer did not verify: {exc}"
            ) from exc
        except SiteCapacityClientError as exc:
            if exc.status_code is None:
                raise PoolOverrideRefused(503, f"site {site_id!r} is unreachable: {exc}") from exc
            raise PoolOverrideRefused(
                503, f"site {site_id!r} answered HTTP {exc.status_code}: {exc}"
            ) from exc
        revision = answer.get("revision") if isinstance(answer, Mapping) else None
        digest = answer.get("digest") if isinstance(answer, Mapping) else None
        pools = answer.get("resource_pools") if isinstance(answer, Mapping) else None
        # A verified answer can still be skewed; one that is not a list of pool
        # objects cannot be judged, and failing on it later would be a 500.
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(digest, str)
            or not isinstance(pools, list)
            or not all(isinstance(pool, Mapping) for pool in pools)
        ):
            raise PoolOverrideRefused(
                503, f"site {site_id!r} returned an unusable resource-pool projection"
            )
        return revision, digest, pools

    async def _after_write(self, site_id: str) -> None:
        # The next cycle reads the stored override itself; the refresh only
        # brings the cache up to the generation the write was checked against,
        # and the wake makes the effect prompt. The write already stands, so a
        # refresh failure is logged rather than raised.
        try:
            await self._refresh_site(site_id)
        except Exception:
            logger.exception(
                "[POOL-OVERRIDES] refreshing site %s's projection after a write failed",
                site_id,
            )
        self._wake_publication()

    async def get(self, address: PoolOverrideAddress) -> dict[str, Any] | None:
        return await self._store.get(address)

    async def list(
        self, *, site_id: str | None = None, pool_id: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._store.list(site_id=site_id, pool_id=pool_id)

    async def delete(self, address: PoolOverrideAddress) -> bool:
        """Remove an override. Idempotent; contacts no site.

        A delete verifies no pool, so it has no newer generation to bring the
        cache to; it only wakes publication so the next tier applies promptly.
        """
        deleted = await self._store.delete(address)
        self._wake_publication()
        return deleted

    async def statuses(self) -> list[dict[str, Any]]:
        """Every stored override's address and the one state it is in."""
        site_ids = set(self._site_ids())
        projection = self._projection_source()
        return [
            {
                "site_id": override["site_id"],
                "pool_id": override["pool_id"],
                "offering_mode": override["offering_mode"],
                "state": override_state(
                    site_id=override["site_id"],
                    pool_id=override["pool_id"],
                    site_ids=site_ids,
                    projection=projection,
                ),
            }
            for override in await self._store.list()
        ]


__all__ = [
    "OVERRIDE_APPLIED",
    "OVERRIDE_INACTIVE",
    "OVERRIDE_ORPHANED",
    "OVERRIDE_SITE_UNCONFIGURED",
    "OVERRIDE_UNKNOWN",
    "PoolOverrideRefused",
    "PoolOverrideService",
    "ProjectionSource",
    "override_state",
]
