"""Rechecking a bare-metal listing against its source when a negotiation opens.

The check itself is the domain's (``recheck_bare_metal_listing_source``). This
module supplies what the domain function leaves to its caller: the listing's
binding and published shape, the bound site's live projection fetched through
that site's own trusted client, and each pool's admission and region read
exactly as publication reads them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from arkhai_bare_metal import (
    SOURCE_ABSENT,
    ListingSourceCheck,
    recheck_bare_metal_listing_source,
    trusted_bare_metal_projection,
)

from .site_reading import read_site_pools
from .sqlite_client import SQLiteClient

#: Recheck one listing against its source, as seller policy consults it.
ListingSourceGuard = Callable[[str], Awaitable[ListingSourceCheck]]


class ListingSourceUnverifiable(RuntimeError):
    """The listing's site could not answer with a projection this storefront trusts.

    Retryable: the listing is not known to be wrong, only not known to be right.
    """


def build_listing_source_guard(
    db: SQLiteClient, site_client: Callable[[str], Any]
) -> ListingSourceGuard:
    """A guard reading each listing's own site through ``site_client``."""

    async def recheck(listing_id: str) -> ListingSourceCheck:
        binding = await db.load_listing_binding(listing_id=listing_id)
        listing = await db.load_bare_metal_listing_payload(listing_id=listing_id)
        if (
            binding is None
            or listing is None
            or not binding.pool_id
            or not binding.physical_resource_id
        ):
            return ListingSourceCheck(SOURCE_ABSENT, "the listing has no trusted source binding")
        try:
            response = await site_client(binding.site_id).resource_pool_projection()
            generation = trusted_bare_metal_projection(
                site_id=binding.site_id, projection=response
            )
        except Exception as exc:
            raise ListingSourceUnverifiable(
                f"site {binding.site_id!r} could not confirm the listing's source: {exc}"
            ) from exc
        reading = read_site_pools(response["resource_pools"])
        return recheck_bare_metal_listing_source(
            generation,
            pool_admission=reading.admission,
            pool_regions=reading.regions,
            pool_id=binding.pool_id,
            physical_resource_id=binding.physical_resource_id,
            shape_digest=listing.shape_digest,
            region=listing.region,
        )

    return recheck


__all__ = [
    "ListingSourceGuard",
    "ListingSourceUnverifiable",
    "build_listing_source_guard",
]
