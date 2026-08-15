"""`market listing` — read-only views over the listing registry.

Pure buyers don't run a storefront, so this module only covers
operations that hit the operator-run listing registry:

    market listing list           # browse open listings
    market listing show <id>      # inspect a single listing

Listing publication, closing, refunds, claims, and discovery used to
live here too, but those endpoints live on a storefront and only made
sense in the symmetric era when buyers also ran agents. They moved
out with the buyer-as-pure-client refactor.
"""

from __future__ import annotations


import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from core_buyer import build_buyer_explanation, explain_registry_query

from .buy_orchestrator import query_registry_for_matches_multi
from .cli_helpers import emit_buyer_explanation
from .settlement_composition import resolve_buyer_settlement_policy
from domains.vms.listings import (
    format_accepted_escrows,
    format_demands,
    format_resource,
    short_ts,
    shorten,
)
from market_settlement_runtime import settlement_clause_descriptors


listing_app = typer.Typer(no_args_is_help=True)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _normalize_registry_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


def settlement_clause_error_message(exc: ValueError, policy) -> str:
    """Render a clause failure with the generated buyer field vocabulary."""

    descriptors = settlement_clause_descriptors(policy.registry, role="buyer")
    accepted = sorted(
        {
            name
            for descriptor in descriptors
            for name in (descriptor.name, *descriptor.aliases)
        }
    )
    return f"{exc}. Accepted settlement fields: {', '.join(accepted)}"


def _registry_context(
    *,
    registry_urls: str | None,
    discovery_timeout: float | None,
):
    """Resolve one signer-authenticated, authority-pinned registry set."""
    from .common import (
        VMS_SCHEMA_ID,
        resolve_discovery_timeout,
        resolve_fresh_buyer_identity,
        resolve_indexer_urls,
        resolve_indexer_urls_for_schema,
        resolve_registry_api_keys,
        resolve_registry_authorities,
    )

    identity = resolve_fresh_buyer_identity()
    signer = identity.signer
    configured_urls = resolve_indexer_urls(override=registry_urls)
    authorities = resolve_registry_authorities(configured_urls)
    deadline = resolve_discovery_timeout(override=discovery_timeout)
    urls = resolve_indexer_urls_for_schema(
        VMS_SCHEMA_ID,
        signer=signer,
        registry_authorities=authorities,
        override=registry_urls,
        timeout=deadline,
    )
    authorities = {url: authorities[url] for url in urls}
    api_keys = {
        url: key
        for url, key in resolve_registry_api_keys().items()
        if url in authorities
    }
    return identity, signer, urls, authorities, api_keys, deadline


# ---------------------------------------------------------------------------
# market listing list
# ---------------------------------------------------------------------------


@listing_app.command("list")
def listing_list(
    registry_urls: str = typer.Option(
        None,
        "--registry-urls",
        "-r",
        help="Comma-separated listing registry base URLs "
        "(config.toml: registry.urls). The result is the union "
        "across all registries, deduped by listing_id.",
    ),
    discovery_timeout: float | None = typer.Option(
        None,
        "--discovery-timeout",
        help="Per-registry deadline in seconds (default: "
        "registry.discovery_timeout from config.toml, fallback 5).",
    ),
    resource_query: str | None = typer.Option(
        None,
        "--resource",
        help="Typed resource constraints, for example "
        "'gpu_model in [H200,A100] ram_gb>=64 static_ip=true'.",
    ),
    settlement: list[str] | None = typer.Option(
        None,
        "--settlement",
        help="Repeatable typed settlement alternative, for example "
        "'mechanism=stripe asset=usd stripe.method=card'.",
    ),
    explain: bool = typer.Option(
        False,
        "--explain",
        help="Render a read-only selection plan and stop before negotiation.",
    ),
    # Pagination
    limit: int = typer.Option(
        50, "--limit", "-l", help="Maximum listings to fetch (1-200)."
    ),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset."),
) -> None:
    """List open listings matching an optional typed resource query."""
    try:
        settlement_policy = resolve_buyer_settlement_policy()
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    try:
        settlement_clauses = settlement_policy.compile_clauses(settlement or ())
    except ValueError as exc:
        raise typer.BadParameter(
            settlement_clause_error_message(exc, settlement_policy)
        ) from exc
    identity, signer, urls, authorities, api_keys, deadline = _registry_context(
        registry_urls=registry_urls,
        discovery_timeout=discovery_timeout,
    )
    try:
        settlement_policy = resolve_buyer_settlement_policy(identity=identity)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if limit < 1 or limit > 200:
        raise typer.BadParameter("limit must be between 1 and 200")
    if offset < 0:
        raise typer.BadParameter("offset must be >= 0")

    discovery = None
    if explain:
        discovery = explain_registry_query(
            urls,
            timeout=deadline,
            signer=signer,
            registry_authorities=authorities,
            resource_query=resource_query,
            limit=limit,
            offset=offset,
            api_keys=api_keys,
        )
        rows = list(discovery.listings)
    else:
        rows = query_registry_for_matches_multi(
            urls,
            timeout=deadline,
            signer=signer,
            registry_authorities=authorities,
            resource_query=resource_query,
            limit=limit,
            offset=offset,
            api_keys=api_keys,
        )

    if explain:
        assert discovery is not None

        trace = settlement_policy.explain_listings(
            rows,
            expiration_unix=2_000_000_000,
            clauses=settlement_clauses,
        )
        emit_buyer_explanation(build_buyer_explanation(discovery, trace))
        return

    selected_rows = settlement_policy.select_listings(
        rows,
        expiration_unix=2_000_000_000,
        clauses=settlement_clauses,
    )
    items = []
    for row, selected in selected_rows:
        normalized = dict(row)
        normalized["_selected_settlement"] = selected
        items.append(normalized)
    console = Console()
    table = Table(title="Open Listings", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Listing ID", style="bold", overflow="fold")
    table.add_column("Publisher")
    table.add_column("Storefront URL")
    table.add_column("Offer")
    table.add_column("Accepted escrows")
    table.add_column("Settlement")
    table.add_column("Demands")
    table.add_column("Created", justify="right")

    for row in items:
        offer_display = format_resource(row.get("offer_resource", {}))
        accepted_display = format_accepted_escrows(row.get("accepted_escrows", []))
        demands_display = format_demands(row.get("demands", []))
        selected = row["_selected_settlement"].option
        table.add_row(
            str(row.get("listing_id", "-")),
            str(row.get("publisher_id", "-")),
            shorten(str(row.get("storefront_url", "-")), 40),
            offer_display if "\n" in offer_display else shorten(offer_display, 120),
            accepted_display
            if "\n" in accepted_display
            else shorten(accepted_display, 120),
            f"{selected.mechanism} {selected.asset}",
            demands_display
            if "\n" in demands_display
            else shorten(demands_display, 120),
            short_ts(row.get("created_at")),
        )

    if not items:
        console.print("No open listings found.")
        return

    console.print(table)


# ---------------------------------------------------------------------------
# market listing show
# ---------------------------------------------------------------------------


@listing_app.command("show")
def listing_show(
    listing_id: str = typer.Argument(..., help="Listing ID"),
    registry_urls: str = typer.Option(
        None,
        "--registry-urls",
        "-r",
        help="Comma-separated listing registry base URLs "
        "(config.toml: registry.urls). The first registry that "
        "knows the listing wins; others are skipped.",
    ),
    discovery_timeout: float | None = typer.Option(
        None,
        "--discovery-timeout",
        help="Per-registry deadline in seconds (default: "
        "registry.discovery_timeout from config.toml, fallback 5).",
    ),
) -> None:
    """Show a single listing by ID, fetched from the configured
    listing registries — the first one that knows the listing wins."""
    _identity, signer, urls, authorities, api_keys, deadline = _registry_context(
        registry_urls=registry_urls,
        discovery_timeout=discovery_timeout,
    )
    from .buy_orchestrator import fetch_listing_dict_multi

    try:
        found = fetch_listing_dict_multi(
            urls,
            listing_id,
            timeout=deadline,
            signer=signer,
            registry_authorities=authorities,
            api_keys=api_keys,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if found is None:
        typer.secho(
            f"Listing {listing_id!r} not found in any of {len(urls)} registries.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Listing ID", str(found.get("listing_id", "-")))
    table.add_row("Publisher", str(found.get("publisher_id", "-")))
    table.add_row("Status", str(found.get("status", "-")))
    table.add_row("Storefront URL", str(found.get("storefront_url", "-")))
    max_secs = found.get("max_duration_seconds")
    table.add_row(
        "Max duration (s)",
        str(max_secs) if max_secs else "unlimited",
    )
    table.add_row("Created", short_ts(found.get("created_at")))
    table.add_row("Updated", short_ts(found.get("updated_at")))
    table.add_row("Offer", format_resource(found.get("offer_resource", {})))
    table.add_row(
        "Accepted escrows", format_accepted_escrows(found.get("accepted_escrows", []))
    )
    table.add_row("Demands", format_demands(found.get("demands", [])))

    console.print(Panel(table, title="Marketplace Listing", border_style="blue"))
