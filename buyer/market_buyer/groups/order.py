"""`market order` — read-only views over the registry indexer.

Pure buyers don't run a storefront, so this module only covers
operations that hit the operator-run registry indexer:

    market order list           # browse open orders
    market order show <id>      # inspect a single order

Order publication, closing, refunds, claims, and discovery used to
live here too, but those endpoints live on a storefront and only made
sense in the symmetric era when buyers also ran agents. They moved
out with the buyer-as-pure-client refactor.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..common import resolve_config_value


order_app = typer.Typer(no_args_is_help=True)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _normalize_registry_url(raw_url: str) -> str:
    return raw_url.rstrip("/")


def _short_contract_address(value: str) -> str:
    if not value:
        return "-"
    if len(value) <= 12:
        return value
    return f"{value[:6]}…{value[-4:]}"


def _format_resource(resource: dict) -> str:
    if not resource:
        return "-"
    if not isinstance(resource, dict):
        return str(resource)
    is_compute = resource.get("type") == "compute" or "gpu_model" in resource
    if is_compute:
        ordered_keys = ("type", "gpu_model", "quantity", "sla", "region")
        lines = [f"{key}={resource[key]}" for key in ordered_keys if key in resource]
        extra_keys = sorted(k for k in resource.keys() if k not in ordered_keys)
        lines.extend(f"{key}={resource[key]}" for key in extra_keys)
        return "\n".join(lines) if lines else "-"
    if "token" in resource:
        token = resource.get("token", {})
        amount = resource.get("amount")
        lines = []
        if isinstance(token, dict):
            symbol = token.get("symbol")
            contract = token.get("contract_address")
            if symbol:
                lines.append(f"symbol={symbol}")
            if contract:
                lines.append(f"contract_address={_short_contract_address(str(contract))}")
        if amount is not None:
            lines.append(f"amount={amount}")
        return "\n".join(lines) if lines else "-"
    return json.dumps(resource, separators=(",", ":"), sort_keys=True)


def _shorten(text: str, width: int = 36) -> str:
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _short_ts(value: str | None) -> str:
    if not value:
        return "-"
    return value.split(".")[0].replace("T", " ")


def _fetch_json(url: str) -> dict:
    """GET a JSON document from the registry indexer."""
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8") if exc.fp else str(exc)
        typer.secho(f"Registry error ({exc.code}): {detail}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Failed to fetch from registry: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# market order list
# ---------------------------------------------------------------------------


@order_app.command("list")
def order_list(
    registry_url: str = typer.Option(
        None,
        "--registry-url",
        "-r",
        help="Registry indexer base URL (config.toml: registry.url).",
    ),
    order_id: str | None = typer.Option(
        None,
        "--order-id",
        help="Filter by order ID.",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        help="Maximum orders to fetch (1-200).",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        "-o",
        help="Pagination offset.",
    ),
) -> None:
    """List open orders from the registry indexer."""
    base_url = (
        registry_url
        or resolve_config_value(toml_path="registry.url")
        or "http://localhost:8080"
    )
    base_url = _normalize_registry_url(base_url)
    if limit < 1 or limit > 200:
        raise typer.BadParameter("limit must be between 1 and 200")
    if offset < 0:
        raise typer.BadParameter("offset must be >= 0")

    query_params: dict[str, str | int] = {"status": "open", "limit": limit, "offset": offset}
    if order_id:
        query_params["order_id"] = order_id
    params = urllib.parse.urlencode(query_params)
    url = f"{base_url}/orders?{params}"

    payload = _fetch_json(url)

    items = payload.get("items", [])
    console = Console()
    table = Table(title="Open Orders", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Order ID", style="bold", overflow="fold")
    table.add_column("Agent ID")
    table.add_column("Maker")
    table.add_column("Taker")
    table.add_column("Offer")
    table.add_column("Demand")
    table.add_column("Created", justify="right")

    for order in items:
        offer_display = _format_resource(order.get("offer_resource", {}))
        demand_display = _format_resource(order.get("demand_resource", {}))
        table.add_row(
            str(order.get("order_id", "-")),
            _shorten(str(order.get("agent_id", "-")), 32),
            _shorten(str(order.get("order_maker", "-")), 40),
            _shorten(str(order.get("order_taker", "-")), 40),
            offer_display if "\n" in offer_display else _shorten(offer_display, 120),
            demand_display if "\n" in demand_display else _shorten(demand_display, 120),
            _short_ts(order.get("created_at")),
        )

    if not items:
        console.print("No open orders found.")
        return

    console.print(table)


# ---------------------------------------------------------------------------
# market order show
# ---------------------------------------------------------------------------


@order_app.command("show")
def order_show(
    order_id: str = typer.Argument(..., help="Order ID"),
    registry_url: str = typer.Option(
        None,
        "--registry-url",
        "-r",
        help="Registry indexer base URL (config.toml: registry.url).",
    ),
) -> None:
    """Show a single order by ID, fetched from the registry indexer."""
    base_url = (
        registry_url
        or resolve_config_value(toml_path="registry.url")
        or "http://localhost:8080"
    )
    base_url = _normalize_registry_url(base_url)
    url = f"{base_url}/orders/{order_id}"
    payload = _fetch_json(url)
    found = payload.get("order", payload)

    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Order ID", str(found.get("order_id", "-")))
    table.add_row("Agent ID", str(found.get("agent_id", "-")))
    table.add_row("Status", str(found.get("status", "-")))
    table.add_row("Maker", str(found.get("order_maker", "-")))
    table.add_row("Taker", str(found.get("order_taker", "-")))
    table.add_row("Duration (h)", str(found.get("duration_hours", "-")))
    table.add_row("Created", _short_ts(found.get("created_at")))
    table.add_row("Updated", _short_ts(found.get("updated_at")))
    table.add_row("Offer", _format_resource(found.get("offer_resource", {})))
    table.add_row("Demand", _format_resource(found.get("demand_resource", {})))

    console.print(Panel(table, title="Market Order", border_style="blue"))
