"""A seller's close, and an operator's pause and resume, of one bare-metal listing.

Both act through the capacity-publication kit's publication runtime over the
listing's durable binding, as a publication cycle does, so the close a seller
makes is the one every later write keeps: no reconciliation reopens it, and a
publication cycle skips its listing. A pause leaves the listing open and
published while new negotiations on it are refused. Resume clears the pause and
re-lists it: a listing its seller closed is reopened locally and at every
registry, and an open one is republished. A listing reconciliation closed is
not the seller's to re-list; it reopens when its source supports it again. See
openspec/specs/storefront-publication/spec.md, "A seller's close is durable".
"""

from __future__ import annotations

import sqlite3
from typing import Any

from market_capacity_publication import BoundListing, PublicationRuntime

from .listing_binding import bare_metal_listing_binding
from .publication_service import bare_metal_publication_candidate, build_publication_runtime
from .runtime import BareMetalStorefrontRuntime


class ListingControlError(Exception):
    """A close or resume refused, with the status and detail it answers."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _publication(runtime: BareMetalStorefrontRuntime) -> PublicationRuntime[dict[str, Any]]:
    """The kit's publication runtime over every registry the storefront publishes to."""
    registries = runtime.registry_configuration
    if registries is None:
        raise ListingControlError(503, "no registry is configured for publication")
    return build_publication_runtime(
        runtime.db,
        registries.client_factory(runtime.marketplace_signer),
        registry_urls=registries.urls,
        storefront_url=runtime.storefront_url,
    )


async def close_listing_as_seller(
    runtime: BareMetalStorefrontRuntime, listing_id: str
) -> dict[str, Any]:
    """Close the listing as its seller, locally and then at every registry.

    A database that cannot be written, a lock another writer holds past the
    busy timeout among them, answers 503 for the seller to retry; a close is
    idempotent, so a retry after one that did complete keeps the seller's close.
    """
    try:
        binding = await bare_metal_listing_binding(runtime.db, listing_id)
        if binding is None:
            raise ListingControlError(404, "listing not found")
        result = await _publication(runtime).close(
            BoundListing(listing_id, binding), closed_by="seller"
        )
    except sqlite3.OperationalError as exc:
        raise ListingControlError(
            503,
            {
                "error": "listing_close_incomplete",
                "hint": "The listing is unchanged; retry the close.",
            },
        ) from exc
    return {"status": result.get("status", "closed"), "listing_id": listing_id}


async def pause_listing(
    runtime: BareMetalStorefrontRuntime, listing_id: str
) -> dict[str, Any]:
    """Pause the listing: it stays published, and new negotiations on it are refused."""
    if await runtime.db.load_listing(listing_id=listing_id) is None:
        raise ListingControlError(404, "listing not found")
    await runtime.db.set_listing_paused(listing_id=listing_id, paused=True)
    return {
        "listing_id": listing_id,
        "paused": True,
        "message": "Listing paused. New negotiations will receive 503.",
    }


async def resume_listing(
    runtime: BareMetalStorefrontRuntime, listing_id: str
) -> dict[str, Any]:
    """Clear the listing's pause and re-list it, as its operator asks."""
    stored = await runtime.db.load_listing(listing_id=listing_id)
    binding = await bare_metal_listing_binding(runtime.db, listing_id)
    if stored is None or binding is None:
        raise ListingControlError(404, "listing not found")
    closed = stored.get("status") == "closed"
    if closed and stored.get("closed_by") != "seller":
        raise ListingControlError(
            409,
            {
                "error": "listing_closed_by_reconciliation",
                "closed_by": stored.get("closed_by"),
                "hint": (
                    "Its source does not currently support this listing; it "
                    "reopens when the source does."
                ),
            },
        )
    publication = _publication(runtime)
    candidate = await bare_metal_publication_candidate(runtime.db, listing_id)
    await runtime.db.set_listing_paused(listing_id=listing_id, paused=False)
    if closed:
        result = await publication.reopen(candidate, reopened_by="seller")
    else:
        result = await publication.publish(candidate)
    registry_status = str(result.get("status", "unknown"))
    return {
        "listing_id": listing_id,
        "paused": False,
        "registry_status": registry_status,
        "message": f"Listing resumed and {registry_status} to registry.",
    }


__all__ = [
    "ListingControlError",
    "close_listing_as_seller",
    "pause_listing",
    "resume_listing",
]
