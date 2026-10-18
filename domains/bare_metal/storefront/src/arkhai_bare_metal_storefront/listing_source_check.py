"""Rechecking a bare-metal listing against its own source.

The negotiation runtime asks before every seller decision and every acceptance.
The check itself is the domain's (``recheck_bare_metal_listing_source``). This
module supplies what the domain function leaves to its caller: the listing's
binding and published shape, the resource-pool projection the storefront holds
for the bound site, its bare-metal views accepted as publication accepts them,
and each pool's admission and region read exactly as publication reads them,
with each pool's backing delegate. No site is called. It answers with the
policy kit's ``ListingSourceVerdict``, which the runtime enforces.

Only a freshly confirmed generation confirms a listing: the site's most recent
poll succeeded within the storefront's source-confirmation window. A site whose
projection is not held, whose latest poll failed, whose confirmation is older
than the window, or whose generation this domain refuses cannot confirm the
listing, which is retryable rather than a mismatch; the window bounds how far
the availability and declarations a recheck relies on lag the site. Admission at
the site stays authoritative. See openspec/specs/storefront-publication/spec.md,
"Bare-metal opening rechecks its listing against its source".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from arkhai_bare_metal import (
    SOURCE_MATCHES,
    SOURCE_UNAVAILABLE,
    recheck_bare_metal_listing_source,
    trusted_bare_metal_projection,
)
from market_capacity_publication import (
    RESOURCE_POOL,
    CapacityBindingError,
    SiteProjectionState,
    backing_changed,
    freshly_confirmed,
)
from market_policy.listing_source import ListingSourceVerdict

from .listing_binding import bare_metal_listing_binding
from .site_reading import read_site_pools
from .sqlite_client import SQLiteClient

#: Check one listing, by id, against its own source.
ListingSourceCheck = Callable[[str], Awaitable[ListingSourceVerdict]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def build_listing_source_check(
    db: SQLiteClient,
    site_projections: SiteProjectionState | None,
    *,
    confirmation_window_seconds: float,
    clock: Callable[[], datetime] = _utc_now,
) -> ListingSourceCheck:
    """A check reading each listing's own site from ``site_projections``.

    ``clock`` is the time a confirmation's age is measured at. With no
    projection state no trusted site authority is composed, so no listing can
    be confirmed: every check is unverifiable, and retryable.
    """

    async def check(listing_id: str) -> ListingSourceVerdict:
        if site_projections is None:
            return ListingSourceVerdict(
                "unverifiable", "the listing's site authority is not configured"
            )
        binding = await db.load_listing_binding(listing_id=listing_id)
        listing = await db.load_bare_metal_listing_payload(listing_id=listing_id)
        if (
            binding is None
            or listing is None
            or not binding.pool_id
            or not binding.physical_resource_id
        ):
            return ListingSourceVerdict(
                "declared_mismatch", "the listing has no trusted source binding"
            )
        site_id = binding.site_id
        try:
            view = site_projections.view(site_id, RESOURCE_POOL)
        except CapacityBindingError:
            return ListingSourceVerdict(
                "unverifiable", f"site {site_id!r} is not a configured capacity site"
            )
        if view.value is None or view.identity is None:
            return ListingSourceVerdict(
                "unverifiable", f"site {site_id!r} resource_pool projection is not loaded"
            )
        if not freshly_confirmed(
            view, now=clock(), window_seconds=confirmation_window_seconds
        ):
            confirmed = view.fetched_at.isoformat() if view.fetched_at else "never"
            return ListingSourceVerdict(
                "unverifiable",
                f"site {site_id!r} resource_pool projection is not freshly confirmed "
                f"(state {view.state.value}, last confirmed {confirmed}, "
                f"window {confirmation_window_seconds:g}s)",
            )
        response = {
            "revision": view.identity.revision,
            "digest": view.identity.digest,
            "resource_pools": list(view.value),
        }
        try:
            generation = trusted_bare_metal_projection(site_id=site_id, projection=response)
        except ValueError as exc:
            return ListingSourceVerdict(
                "unverifiable",
                f"site {site_id!r} serves a generation bare metal refuses: {exc}",
            )
        reading = read_site_pools(response["resource_pools"])
        # A listing's backing is fixed for the life of its binding, so a pool
        # that now declares another backing is a declared mismatch, decided
        # before anything else is compared.
        source_backing = reading.backings.get(binding.pool_id)
        bound = await bare_metal_listing_binding(db, listing_id)
        if (
            bound is not None
            and source_backing is not None
            and backing_changed(bound, source_backing)
        ):
            return ListingSourceVerdict(
                "declared_mismatch",
                "the pool's backing differs from the listing's",
                ("capacity_backing",),
            )
        result = recheck_bare_metal_listing_source(
            generation,
            pool_admission=reading.admission,
            pool_backings=reading.backings,
            pool_regions=reading.regions,
            pool_id=binding.pool_id,
            physical_resource_id=binding.physical_resource_id,
            shape_digest=listing.shape_digest,
            region=listing.region,
        )
        if result.outcome == SOURCE_MATCHES:
            return ListingSourceVerdict("matches")
        if result.outcome == SOURCE_UNAVAILABLE:
            return ListingSourceVerdict("unavailable", result.reason)
        # A changed declaration and a source that no longer offers the resource
        # are both the listing no longer matching what its source declares.
        return ListingSourceVerdict("declared_mismatch", result.reason)

    return check


__all__ = ["ListingSourceCheck", "build_listing_source_check"]
