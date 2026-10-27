"""`market <command> listing` — read-only views over the listing registry.

Fans in across the configured registries that declare the domain's schema,
maps the typed resource query to the registry filter-spec, and renders each
listing's resource through the domain's rendering, its unit price, and the
settlement terms each stage describes.
"""

from __future__ import annotations

from typing import Any

import typer
from core_buyer.orchestrator import fetch_listing_dict_multi, query_registry_for_matches_multi
from core_buyer.policy_surface import extract_seller_min_price
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arkhai_api_buying import common
from arkhai_api_buying.settlement_composition import BuyerSettlementComposition


def shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def short_ts(value: Any) -> str:
    """Trim an ISO timestamp to date + hh:mm for table display."""
    s = str(value or "-")
    return s[:16].replace("T", " ")


def format_unit_price(listing: dict[str, Any]) -> str:
    rate = extract_seller_min_price(listing)
    if rate is None:
        return "-"
    return f"{int(rate)} / token"


def _schema_registries(schema_id: str, registry_urls: str | None, timeout: float | None):
    """The signer and the configured registries declaring ``schema_id``, with their trust and keys."""
    signer = common.resolve_fresh_buyer_identity().signer
    deadline = common.resolve_discovery_timeout(override=timeout)
    authorities = common.resolve_registry_authorities(
        common.resolve_indexer_urls(override=registry_urls)
    )
    urls = common.resolve_indexer_urls_for_schema(
        schema_id,
        signer=signer,
        registry_authorities=authorities,
        override=registry_urls,
        timeout=deadline,
    )
    all_api_keys = common.resolve_registry_api_keys()
    return (
        signer,
        deadline,
        urls,
        {url: authorities[url] for url in urls},
        {url: all_api_keys[url] for url in urls if url in all_api_keys},
    )


def listing_app(settlement: BuyerSettlementComposition) -> typer.Typer:
    """The group's `listing` commands, rendered through the domain's bundle."""
    contributions = settlement.contributions
    rendering = contributions.rendering
    noun = contributions.noun
    app = typer.Typer(no_args_is_help=True)

    @app.command("list", help=f"List open {noun} listings from the listing registry.")
    def listing_list(
        registry_urls: str = typer.Option(
            None,
            "--registry-urls",
            "-r",
            help="Comma-separated listing registry base URLs "
            "(config.toml: registry.urls). The result is the union "
            "across all registries, deduped by registry authority and listing_id.",
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
            help=f"Typed resource constraints, for example {contributions.resource_query_example!r}.",
        ),
        limit: int = typer.Option(
            50, "--limit", "-l", help="Maximum listings to fetch (1-200)."
        ),
        offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset."),
    ) -> None:
        signer, deadline, urls, authorities, api_keys = _schema_registries(
            contributions.schema_id, registry_urls, discovery_timeout
        )
        if limit < 1 or limit > 200:
            raise typer.BadParameter("limit must be between 1 and 200")
        if offset < 0:
            raise typer.BadParameter("offset must be >= 0")
        try:
            items = query_registry_for_matches_multi(
                urls,
                timeout=deadline,
                signer=signer,
                registry_authorities=authorities,
                resource_query=resource_query,
                limit=limit,
                offset=offset,
                api_keys=api_keys,
            )
        except RuntimeError as exc:
            typer.secho(
                f"Registry query failed: {exc}",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        console = Console()
        table = Table(title=f"Open {noun} listings", box=box.SIMPLE_HEAVY, expand=True)
        table.add_column("Listing ID", style="bold", overflow="fold")
        table.add_column(rendering.summary_header)
        table.add_column("Unit price", justify="right")
        for header, _value in rendering.columns:
            table.add_column(header)
        table.add_column("Storefront URL")
        table.add_column("Created", justify="right")

        for row in items:
            resource = rendering.resource(row.get("listing_resource", {}))
            table.add_row(
                str(row.get("listing_id", "-")),
                rendering.summary(resource),
                format_unit_price(row),
                *(shorten(value(resource), 40) for _header, value in rendering.columns),
                shorten(str(row.get("storefront_url", "-")), 40),
                short_ts(row.get("created_at")),
            )

        if not items:
            console.print(f"No open {noun} listings found.")
            return

        console.print(table)

    @app.command("show", help=f"Show a single {noun} listing by ID.")
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
        signer, deadline, urls, authorities, api_keys = _schema_registries(
            contributions.schema_id, registry_urls, discovery_timeout
        )
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

        resource = rendering.resource(found.get("listing_resource", {}))
        console = Console()
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        table.add_row("Listing ID", str(found.get("listing_id", "-")))
        table.add_row("Publisher", str(found.get("publisher_id", "-")))
        table.add_row("Status", str(found.get("status", "-")))
        table.add_row("Storefront URL", str(found.get("storefront_url", "-")))
        for label, value in rendering.details(resource):
            table.add_row(label, value)
        table.add_row("Unit price", format_unit_price(found))
        table.add_row("Created", short_ts(found.get("created_at")))
        table.add_row("Updated", short_ts(found.get("updated_at")))
        for stage in settlement.stages.values():
            for label, value in stage.listing_rows(found):
                table.add_row(label, value)

        console.print(Panel(table, title=f"{noun} listing", border_style="blue"))

    return app
