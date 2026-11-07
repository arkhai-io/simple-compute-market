"""`bare-metal-storefront publish`: one cycle of the storefront's publication loop.

Publication runs inside the storefront as a lifecycle loop over the site
projections it holds. This command is a client of that loop: it runs, or
previews, exactly the cycle the loop's timer runs, through the storefront's
administrator API, whether or not the loops are held, and reports what the
cycle did or would do; or, with ``--abort-all``, closes every open listing as
its seller. It never reads or writes the storefront's database and
never publishes on its own. It signs and connects as ``admin_cli`` says. See
openspec/specs/storefront-publication/spec.md, "Publication runs as a
controllable storefront lifecycle loop".
"""

from __future__ import annotations

from typing import Any

from .admin_cli import storefront_admin_client, storefront_seller_client

#: The publication loop's lifecycle route.
PUBLICATION_ROUTE = "publication"


def run_publication_cycle(storefront_url: str | None, *, dry_run: bool) -> dict[str, Any]:
    """Run one publication cycle, or with ``dry_run`` preview one, and return its report."""
    with storefront_admin_client(storefront_url) as client:
        if dry_run:
            return client.admin_dry_run_lifecycle_cycle(PUBLICATION_ROUTE)
        return client.admin_run_lifecycle_cycle(PUBLICATION_ROUTE)


def close_all_open_listings(storefront_url: str | None) -> list[str]:
    """Close every open listing as its seller, which reconciliation will not undo.

    A seller's close is durable: no publication cycle reopens it, and an
    administrator's resume re-lists one.
    """
    closed: list[str] = []
    with storefront_seller_client(storefront_url) as client:
        while True:
            page = client.list_listings(status="open", limit=200)
            if not page.listings:
                return closed
            for listing in page.listings:
                client.close_listing(listing.listing_id)
                closed.append(listing.listing_id)


__all__ = ["PUBLICATION_ROUTE", "close_all_open_listings", "run_publication_cycle"]
