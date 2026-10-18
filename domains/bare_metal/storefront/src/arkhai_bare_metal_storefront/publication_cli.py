"""`bare-metal-storefront publish`: one cycle of the storefront's publication loop.

Publication runs inside the storefront as a lifecycle loop over the site
projections it holds. This command is a client of that loop: it runs, or
previews, exactly the cycle the loop's timer runs, through the storefront's
administrator API, whether or not the loops are held, and reports what the
cycle did or would do. It never reads or writes the storefront's database and
never publishes on its own. It signs and connects as ``admin_cli`` says. See
openspec/specs/storefront-publication/spec.md, "Publication runs as a
controllable storefront lifecycle loop".
"""

from __future__ import annotations

from typing import Any

from .admin_cli import storefront_admin_client

#: The publication loop's lifecycle route.
PUBLICATION_ROUTE = "publication"


def run_publication_cycle(storefront_url: str | None, *, dry_run: bool) -> dict[str, Any]:
    """Run one publication cycle, or with ``dry_run`` preview one, and return its report."""
    with storefront_admin_client(storefront_url) as client:
        if dry_run:
            return client.admin_dry_run_lifecycle_cycle(PUBLICATION_ROUTE)
        return client.admin_run_lifecycle_cycle(PUBLICATION_ROUTE)


__all__ = ["PUBLICATION_ROUTE", "run_publication_cycle"]
