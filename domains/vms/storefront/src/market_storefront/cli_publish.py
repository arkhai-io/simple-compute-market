"""Top-level `market-storefront publish` command.

Publication runs inside the storefront as a lifecycle loop: each cycle derives
listings from what the configured sites declare, publishes new ones, refreshes
terms, closes what no longer has a source, and reopens what reconciliation
closed. This command is a client of that loop. It runs or previews one cycle,
or withdraws every open listing, through the storefront's own API; it never
reads the storefront's database and never publishes on its own.

Terms of sale come only from durable sources — a pool's pricing hint, the
storefront's per-pool override, and ``[pricing]`` configuration — because the
loop re-derives them on every cycle and a term supplied to one command could not
be reproduced.
"""

from __future__ import annotations

from typing import Any

import typer
from market_identity import TrustedIdentitySet
from rich import box
from rich.console import Console
from rich.table import Table
from storefront_client import StorefrontClientError, SyncStorefrontClient

from .cli_common import resolve_storefront_url

PUBLICATION_LOOP = "publication"


def _admin_client(base_url: str) -> SyncStorefrontClient:
    # Loop controls are administrator routes. The storefront's own signer must
    # be configured under `identity.administrators` for this command to act.
    from .utils.config import resolve_marketplace_signer

    signer = resolve_marketplace_signer()
    return SyncStorefrontClient(
        base_url,
        signer=signer,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    )


def _seller_client(base_url: str) -> SyncStorefrontClient:
    from .utils.config import resolve_marketplace_signer

    signer = resolve_marketplace_signer()
    return SyncStorefrontClient(
        base_url,
        signer=signer,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    )


def run_cycle(base_url: str, *, dry_run: bool) -> dict[str, Any]:
    """Run or preview one cycle of the storefront's publication loop."""
    with _admin_client(base_url) as client:
        if dry_run:
            return client.admin_dry_run_lifecycle_cycle(PUBLICATION_LOOP)
        return client.admin_run_lifecycle_cycle(PUBLICATION_LOOP)


def close_all_open_listings(base_url: str) -> list[str]:
    """Seller-close every open listing, which reconciliation will not undo."""
    closed: list[str] = []
    with _seller_client(base_url) as client:
        while True:
            page = client.list_listings(status="open", limit=200)
            if not page.listings:
                return closed
            for listing in page.listings:
                client.close_listing(listing.listing_id)
                closed.append(listing.listing_id)


def _print_cycle(console: Console, result: dict[str, Any]) -> None:
    title = "Publication cycle (dry run)" if result.get("dry_run") else "Publication cycle"
    table = Table(title=title, box=box.SIMPLE)
    table.add_column("Action")
    table.add_column("Listing / source")
    table.add_column("Reason")
    for action in result.get("actions") or []:
        subject = action.get("listing_id") or action.get("source") or {
            key: action[key]
            for key in ("site_id", "pool_id", "resource_id")
            if key in action
        }
        table.add_row(
            str(action.get("action")),
            str(subject),
            str(action.get("reason") or ""),
        )
    console.print(table)
    counts = result.get("counts") or {}
    console.print(
        ", ".join(f"{name}: {count}" for name, count in counts.items())
        or "Nothing to do."
    )


def register(app: typer.Typer) -> None:
    """Register the top-level `market-storefront publish` command."""

    @app.command("publish")
    def publish(
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Report what one publication cycle would do, and do none of it.",
        ),
        abort_all: bool = typer.Option(
            False,
            "--abort-all",
            help=(
                "Close every open listing as the seller. Reconciliation does not "
                "reopen a listing its seller closed; resume one to re-list it."
            ),
        ),
        storefront_url: str | None = typer.Option(
            None,
            "--storefront-url",
            "-a",
            help="Storefront base URL (default: base_url from storefront.toml).",
        ),
    ) -> None:
        """Run, or preview, one cycle of the storefront's publication loop."""
        console = Console()
        if abort_all and dry_run:
            raise typer.BadParameter("--abort-all cannot be combined with --dry-run")
        base_url = resolve_storefront_url(storefront_url, default_port=8001)
        try:
            if abort_all:
                closed = close_all_open_listings(base_url)
                console.print(f"Closed {len(closed)} listing(s).")
                return
            _print_cycle(console, run_cycle(base_url, dry_run=dry_run))
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc
