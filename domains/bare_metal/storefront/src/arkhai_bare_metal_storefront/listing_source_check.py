"""Rechecking a bare-metal listing against its own source.

The negotiation runtime asks before every seller decision and every acceptance.
The check itself is the domain's (``recheck_bare_metal_listing_source``). This
module supplies what the domain function leaves to its caller: the listing's
binding and published shape, the bound site's live projection fetched through
that site's own trusted client, and each pool's admission and region read
exactly as publication reads them. It answers with the policy kit's
``ListingSourceVerdict``, which the runtime enforces.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from arkhai_bare_metal import (
    SOURCE_MATCHES,
    SOURCE_UNAVAILABLE,
    recheck_bare_metal_listing_source,
    trusted_bare_metal_projection,
)
from market_policy.listing_source import ListingSourceVerdict

from .site_reading import read_site_pools
from .sqlite_client import SQLiteClient

#: Check one listing, by id, against its own source.
ListingSourceCheck = Callable[[str], Awaitable[ListingSourceVerdict]]


def build_listing_source_check(
    db: SQLiteClient, site_client: Callable[[str], Any] | None
) -> ListingSourceCheck:
    """A check reading each listing's own site through ``site_client``.

    With no ``site_client`` no trusted site authority is composed, so no listing
    can be confirmed: every check is unverifiable, and retryable.
    """

    async def check(listing_id: str) -> ListingSourceVerdict:
        if site_client is None:
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
        try:
            response = await site_client(binding.site_id).resource_pool_projection()
            generation = trusted_bare_metal_projection(
                site_id=binding.site_id, projection=response
            )
        except Exception as exc:  # noqa: BLE001 - any failure leaves the source unknown
            return ListingSourceVerdict(
                "unverifiable",
                f"site {binding.site_id!r} could not confirm the listing's source: {exc}",
            )
        reading = read_site_pools(response["resource_pools"])
        result = recheck_bare_metal_listing_source(
            generation,
            pool_admission=reading.admission,
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
