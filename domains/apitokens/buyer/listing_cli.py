"""`market tokens listing` — read-only views over the listing registry.

Mirrors the VM plugin's listing verbs at the same altitude: fan-in
across the configured registries (filtered to those declaring the
api-tokens schema), named filter flags mapped to the registry
filter-spec, and rendered output — service name, per-token unit price,
and the OpenAPI URL a buyer evaluates an offering by.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core_buyer.policy_surface import extract_seller_min_price
from domains.apitokens.listings import coerce_resource_dict

from .common import build_token_filter_params


listing_app = typer.Typer(no_args_is_help=True)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def short_ts(value: Any) -> str:
    """Trim an ISO timestamp to date + hh:mm for table display."""
    s = str(value or "-")
    return s[:16].replace("T", " ")


def format_offer(resource: Any) -> str:
    """One-line summary of an api_tokens.v1 offer_resource."""
    offer = coerce_resource_dict(resource)
    if not offer:
        return "-"
    parts = [str(offer.get("service_name") or "-")]
    if offer.get("description"):
        parts.append(shorten(str(offer["description"]), 48))
    return " — ".join(parts)


def format_unit_price(listing: dict[str, Any]) -> str:
    rate = extract_seller_min_price(listing)
    if rate is None:
        return "-"
    return f"{int(rate)} / token"


def format_accepted_escrows(raw: Any) -> str:
    """Compact per-entry summary: chain, token, per-token rate."""
    entries = raw
    if isinstance(entries, str):
        try:
            entries = json.loads(entries)
        except (ValueError, TypeError):
            return shorten(str(raw), 60)
    if not isinstance(entries, list) or not entries:
        return "-"
    from market_alkahest.schemas import accepted_token_address, primary_rate_value

    lines = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        token = accepted_token_address(entry) or "-"
        rate = primary_rate_value(entry)
        lines.append(
            f"{entry.get('chain_name', '-')}: {shorten(str(token), 14)}"
            + (f" @ {rate}/token" if rate is not None else " (hidden reserve)")
        )
    return "\n".join(lines) or "-"


# ---------------------------------------------------------------------------
# market tokens listing list
# ---------------------------------------------------------------------------


@listing_app.command("list")
def listing_list(
    registry_urls: str = typer.Option(
        None, "--registry-urls", "-r",
        help="Comma-separated listing registry base URLs "
             "(config.toml: registry.urls). The result is the union "
             "across all registries, deduped by listing_id.",
    ),
    discovery_timeout: float | None = typer.Option(
        None, "--discovery-timeout",
        help="Per-registry deadline in seconds (default: "
             "registry.discovery_timeout from config.toml, fallback 5).",
    ),
    listing_id: str | None = typer.Option(None, "--listing-id", help="Filter by listing ID."),
    service_name: str | None = typer.Option(
        None, "--service-name",
        help="Filter by service name (registry-side contains match).",
    ),
    raw_filters: list[str] | None = typer.Option(
        None, "--filter", "-f",
        help="Registry filter-spec parameter as name=value. Repeatable. "
             "Use this for schema-specific filters that do not have a "
             "convenience flag.",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum listings to fetch (1-200)."),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset."),
) -> None:
    """List open API-token listings from the listing registry."""
    from core_buyer.cli import parse_filter_options

    from .common import (
        APITOKENS_SCHEMA_ID, resolve_indexer_urls_for_schema,
        resolve_discovery_timeout, resolve_indexer_auth,
    )
    urls = [
        u.rstrip("/")
        for u in resolve_indexer_urls_for_schema(APITOKENS_SCHEMA_ID, override=registry_urls)
    ]
    deadline = resolve_discovery_timeout(override=discovery_timeout)
    auth = resolve_indexer_auth()
    if limit < 1 or limit > 200:
        raise typer.BadParameter("limit must be between 1 and 200")
    if offset < 0:
        raise typer.BadParameter("offset must be >= 0")

    query_params: dict[str, str | int] = {"status": "open", "limit": limit, "offset": offset}
    if listing_id:
        query_params["listing_id"] = listing_id
    query_params.update(build_token_filter_params(service_name=service_name))
    query_params.update(parse_filter_options(raw_filters))
    params = urllib.parse.urlencode(query_params)

    # Fan-in across every configured registry; dedupe by listing_id.
    # First-seen wins so the operator's preferred registry (listed
    # first in registry.urls) takes precedence on collisions.
    merged: dict[str, dict] = {}
    successes = 0
    last_error: Exception | None = None
    for base in urls:
        url = f"{base}/listings?{params}"
        try:
            req_headers = {"Accept": "application/json"}
            if auth.get(base):
                req_headers["Authorization"] = f"Bearer {auth[base]}"
            req = urllib.request.Request(url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=deadline) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            typer.secho(
                f"[registry] {base}: {exc}", err=True, fg=typer.colors.YELLOW,
            )
            last_error = exc
            continue
        successes += 1
        for row in payload.get("items", []):
            lid = row.get("listing_id") or row.get("id")
            if lid is None:
                continue
            merged.setdefault(str(lid), row)
    if successes == 0:
        typer.secho(
            f"All {len(urls)} configured registries failed; last error: {last_error}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    items = list(merged.values())
    console = Console()
    table = Table(title="Open API-token listings", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Listing ID", style="bold", overflow="fold")
    table.add_column("Service")
    table.add_column("Unit price", justify="right")
    table.add_column("OpenAPI")
    table.add_column("Storefront URL")
    table.add_column("Created", justify="right")

    for row in items:
        offer = coerce_resource_dict(row.get("offer_resource", {}))
        table.add_row(
            str(row.get("listing_id", "-")),
            format_offer(offer),
            format_unit_price(row),
            shorten(str(offer.get("openapi_url") or "-"), 40),
            shorten(str(row.get("storefront_url", "-")), 40),
            short_ts(row.get("created_at")),
        )

    if not items:
        console.print("No open API-token listings found.")
        return

    console.print(table)


# ---------------------------------------------------------------------------
# market tokens listing show
# ---------------------------------------------------------------------------


@listing_app.command("show")
def listing_show(
    listing_id: str = typer.Argument(..., help="Listing ID"),
    registry_urls: str = typer.Option(
        None, "--registry-urls", "-r",
        help="Comma-separated listing registry base URLs "
             "(config.toml: registry.urls). The first registry that "
             "knows the listing wins; others are skipped.",
    ),
    discovery_timeout: float | None = typer.Option(
        None, "--discovery-timeout",
        help="Per-registry deadline in seconds (default: "
             "registry.discovery_timeout from config.toml, fallback 5).",
    ),
) -> None:
    """Show a single API-token listing by ID."""
    from core_buyer.orchestrator import fetch_listing_dict_multi

    from .common import (
        APITOKENS_SCHEMA_ID, resolve_indexer_urls_for_schema,
        resolve_discovery_timeout, resolve_indexer_auth,
    )
    urls = [
        u.rstrip("/")
        for u in resolve_indexer_urls_for_schema(APITOKENS_SCHEMA_ID, override=registry_urls)
    ]
    deadline = resolve_discovery_timeout(override=discovery_timeout)
    auth = resolve_indexer_auth()
    try:
        found = fetch_listing_dict_multi(urls, listing_id, timeout=deadline, auth=auth)
    except RuntimeError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if found is None:
        typer.secho(
            f"Listing {listing_id!r} not found in any of {len(urls)} registries.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    offer = coerce_resource_dict(found.get("offer_resource", {}))
    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Listing ID", str(found.get("listing_id", "-")))
    table.add_row("Publisher", str(found.get("publisher_id", "-")))
    table.add_row("Status", str(found.get("status", "-")))
    table.add_row("Storefront URL", str(found.get("storefront_url", "-")))
    table.add_row("Service", str(offer.get("service_name") or "-"))
    if offer.get("description"):
        table.add_row("Description", str(offer["description"]))
    table.add_row("OpenAPI URL", str(offer.get("openapi_url") or "-"))
    table.add_row("Base URL", str(offer.get("base_url") or "-"))
    table.add_row("Unit price", format_unit_price(found))
    table.add_row("Created", short_ts(found.get("created_at")))
    table.add_row("Updated", short_ts(found.get("updated_at")))
    table.add_row("Accepted escrows", format_accepted_escrows(found.get("accepted_escrows", [])))

    console.print(Panel(table, title="API-token listing", border_style="blue"))
