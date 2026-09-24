"""Storefront pool overrides: writes checked against the site, and their status.

An override is the storefront's own statement of terms and shapes for one pool
at one site. A write is checked against that site's resource-pool projection,
fetched live through the site's authenticated client rather than read from the
storefront's cache, so neither a stale cache nor a stale refusal decides it.
Derivation reads stored overrides itself; this service only stores them, reports
what each would do, and prompts publication to act on a change.

See openspec/specs/storefront-publication/spec.md, "Storefront pool overrides
are written against the site's live projection".
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Collection, Mapping
from typing import Any

from arkhai_vms import canonical_vm_shape, vm_shape_digest
from market_site_client import SiteCapacityAuthenticationError, SiteCapacityClientError

from market_storefront.models.pool_override_models import PoolOverrideRecord

logger = logging.getLogger(__name__)

#: Judges each of an override's shapes against one site's whole live projection:
#: ``(site_pools, site_id, pool_id, home_site, override) -> {digest: feasible}``.
#: Composed over the derivation publication runs, so a write's report and the
#: next cycle cannot disagree.
ShapeJudge = Callable[
    [list[Mapping[str, Any]], str, str, str, Mapping[str, Any]], Mapping[str, bool]
]

#: Every stored override reports exactly one of these.
OVERRIDE_INACTIVE = "inactive"
OVERRIDE_SITE_UNCONFIGURED = "site_unconfigured"
OVERRIDE_UNKNOWN = "unknown"
OVERRIDE_ORPHANED = "orphaned"
OVERRIDE_APPLIED = "applied"


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

    ``projection`` is the source listings derive from: ``None`` when they
    derive from local tables, where no override applies, and otherwise a
    mapping holding only the sites whose projection is known. A configured
    site missing from it is unknown rather than empty, so its override is never
    called orphaned on the strength of an answer the storefront does not have.
    """
    if projection is None:
        return OVERRIDE_INACTIVE
    if site_id not in site_ids:
        return OVERRIDE_SITE_UNCONFIGURED
    pools = projection.get(site_id)
    if pools is None:
        return OVERRIDE_UNKNOWN
    if any(str(pool.get("resource_pool_id") or "") == pool_id for pool in pools):
        return OVERRIDE_APPLIED
    return OVERRIDE_ORPHANED


class PoolOverrideService:
    """Store, read, and delete overrides; report their status.

    Collaborators are injected so the check order can be proven without a site
    or database: the repository, the capacity runtime whose configured sites
    and signed site clients the write check uses, the source listings derive
    from, the settlement-clause compiler, the shape judge, and the two effects
    a write has on publication.
    """

    def __init__(
        self,
        *,
        sqlite_client: Any,
        capacity_runtime: Any,
        projection_source: Callable[[], Mapping[str, list[Mapping[str, Any]]] | None],
        compile_clauses: Callable[[list[dict[str, Any]]], Any],
        judge_shapes: ShapeJudge,
        refresh_site: Callable[[str], Awaitable[None]],
        wake_publication: Callable[[], None],
    ) -> None:
        self._db = sqlite_client
        self._runtime = capacity_runtime
        self._projection_source = projection_source
        self._compile_clauses = compile_clauses
        self._judge_shapes = judge_shapes
        self._refresh_site = refresh_site
        self._wake_publication = wake_publication

    def _site_ids(self) -> tuple[str, ...]:
        return tuple(self._runtime.site_ids) if self._runtime is not None else ()

    async def replace(self, record: PoolOverrideRecord) -> dict[str, Any]:
        """Check ``record`` against its site's live projection, then store it.

        Refuses, in order and before anything is stored: an unconfigured site or
        clauses that do not compile (422, with no site call); a site that cannot
        be reached or whose answer does not verify (503, retryable); a pool the
        live projection does not hold (404). A shape no member is feasible for
        is reported, not refused.
        """
        site_ids = self._site_ids()
        if record.site_id not in site_ids:
            raise PoolOverrideRefused(
                422, f"site {record.site_id!r} is not a configured capacity site"
            )
        if record.settlements is not None:
            try:
                self._compile_clauses(record.settlements)
            except ValueError as exc:
                raise PoolOverrideRefused(
                    422, f"settlements do not compile: {exc}"
                ) from exc

        revision, digest, site_pools = await self._live_projection(record.site_id)
        if not any(
            str(pool.get("resource_pool_id") or "") == record.pool_id
            for pool in site_pools
        ):
            raise PoolOverrideRefused(
                404,
                f"site {record.site_id!r} does not project pool {record.pool_id!r} "
                f"(projection revision {revision})",
            )

        values = record.model_dump()
        feasible = self._judge_shapes(
            site_pools, record.site_id, record.pool_id, site_ids[0], values
        )
        stored = await self._db.replace_pool_override(values)
        await self._after_write(record.site_id)
        return {
            "override": stored,
            "feasibility": [
                {
                    "shape_digest": vm_shape_digest(shape),
                    "shape": canonical_vm_shape(shape),
                    "feasible": feasible.get(vm_shape_digest(shape), False),
                }
                for shape in record.listing_shapes or ()
            ],
            "projection": {"revision": revision, "digest": digest},
        }

    async def _live_projection(
        self, site_id: str
    ) -> tuple[int, str, list[Mapping[str, Any]]]:
        """Fetch ``site_id``'s resource-pool projection through its signed client.

        Every failure is retryable and names the site and the kind of failure,
        so an operator can tell an unreachable site from an untrusted answer,
        and either from an unknown pool.
        """
        try:
            answer = await self._runtime.site_client(site_id).resource_pool_projection()
        except SiteCapacityAuthenticationError as exc:
            raise PoolOverrideRefused(
                503, f"site {site_id!r} answered, but its answer did not verify: {exc}"
            ) from exc
        except SiteCapacityClientError as exc:
            if exc.status_code is None:
                raise PoolOverrideRefused(
                    503, f"site {site_id!r} is unreachable: {exc}"
                ) from exc
            raise PoolOverrideRefused(
                503, f"site {site_id!r} answered HTTP {exc.status_code}: {exc}"
            ) from exc
        revision = answer.get("revision") if isinstance(answer, Mapping) else None
        digest = answer.get("digest") if isinstance(answer, Mapping) else None
        pools = answer.get("resource_pools") if isinstance(answer, Mapping) else None
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not isinstance(digest, str)
            or not isinstance(pools, list)
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

    async def get(self, *, site_id: str, pool_id: str) -> dict[str, Any] | None:
        return await self._db.get_pool_override(site_id=site_id, pool_id=pool_id)

    async def list(self, *, site_id: str | None = None) -> list[dict[str, Any]]:
        return await self._db.list_pool_overrides(site_id=site_id)

    async def delete(self, *, site_id: str, pool_id: str) -> bool:
        """Remove an override. Idempotent; contacts no site.

        A delete verifies no pool, so it has no newer generation to bring the
        cache to; it only wakes publication so the next tier applies promptly.
        """
        deleted = await self._db.delete_pool_override(site_id=site_id, pool_id=pool_id)
        self._wake_publication()
        return deleted

    async def statuses(self) -> list[dict[str, Any]]:
        """Every stored override with the one state it is in."""
        site_ids = self._site_ids()
        projection = self._projection_source()
        return [
            {
                "site_id": override["site_id"],
                "pool_id": override["pool_id"],
                "state": override_state(
                    site_id=override["site_id"],
                    pool_id=override["pool_id"],
                    site_ids=site_ids,
                    projection=projection,
                ),
            }
            for override in await self._db.list_pool_overrides()
        ]


__all__ = [
    "ShapeJudge",
    "OVERRIDE_APPLIED",
    "OVERRIDE_INACTIVE",
    "OVERRIDE_ORPHANED",
    "OVERRIDE_SITE_UNCONFIGURED",
    "OVERRIDE_UNKNOWN",
    "PoolOverrideRefused",
    "PoolOverrideService",
    "override_state",
]
