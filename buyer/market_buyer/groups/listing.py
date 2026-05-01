"""`market listing` — read-only views over the registry indexer.

Pure buyers don't run a storefront, so this module only covers
operations that hit the operator-run registry indexer:

    market listing list           # browse open listings
    market listing show <id>      # inspect a single listing

Listing publication, closing, refunds, claims, and discovery used to
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


listing_app = typer.Typer(no_args_is_help=True)


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
        ordered_keys = (
            "type", "gpu_model", "gpu_count", "sla", "region",
            "vcpu_count", "ram_gb", "disk_gb", "virtualization_type",
            "cpu_type", "host_cpu_cores", "host_ram_gb", "gpu_interconnect",
        )
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
# market listing list
# ---------------------------------------------------------------------------


@listing_app.command("list")
def listing_list(
    registry_url: str = typer.Option(
        None, "--registry-url", "-r",
        help="Registry indexer base URL (config.toml: registry.url).",
    ),
    listing_id: str | None = typer.Option(None, "--listing-id", help="Filter by listing ID."),
    # Spec filters — slice fields
    gpu_model: str | None = typer.Option(None, "--gpu-model", help="Filter by GPU model (e.g., H200, RTX 5080)."),
    gpu_count_min: int | None = typer.Option(None, "--gpu-count-min", help="Minimum slice GPU count."),
    vcpu_count_min: int | None = typer.Option(None, "--vcpu-min", help="Minimum slice vCPU count."),
    ram_gb_min: int | None = typer.Option(None, "--ram-gb-min", help="Minimum slice RAM (GB)."),
    disk_gb_min: int | None = typer.Option(None, "--disk-gb-min", help="Minimum slice disk (GB)."),
    region: str | None = typer.Option(None, "--region", help="Filter by region."),
    virtualization_type: str | None = typer.Option(
        None, "--virt", help="Virtualization mode (bare_metal|vm|container).",
    ),
    # Spec filters — host context
    cpu_type: str | None = typer.Option(None, "--cpu-type", help="Filter by host CPU model string."),
    host_cpu_cores_min: int | None = typer.Option(None, "--host-cores-min", help="Minimum host CPU cores."),
    host_ram_gb_min: int | None = typer.Option(None, "--host-ram-gb-min", help="Minimum host RAM (GB)."),
    gpu_interconnect: str | None = typer.Option(
        None, "--interconnect", help="GPU interconnect (nvlink|nvswitch|pcie_only|infiniband).",
    ),
    datacenter_grade: bool | None = typer.Option(
        None, "--datacenter/--no-datacenter", help="Restrict to datacenter-grade hosts.",
    ),
    static_ip: bool | None = typer.Option(
        None, "--static-ip/--no-static-ip", help="Restrict to hosts with static public IP.",
    ),
    # Pagination
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum listings to fetch (1-200)."),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset."),
) -> None:
    """List open listings from the registry indexer.

    Spec filters mirror the registry API: equality for strings/enums/bools,
    `_min` semantics for numerics. Without any filters, returns all open
    listings up to ``--limit``.
    """
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
    if listing_id:
        query_params["listing_id"] = listing_id

    spec_filters: dict[str, object] = {
        "gpu_model": gpu_model,
        "gpu_count_min": gpu_count_min,
        "vcpu_count_min": vcpu_count_min,
        "ram_gb_min": ram_gb_min,
        "disk_gb_min": disk_gb_min,
        "region": region,
        "virtualization_type": virtualization_type,
        "cpu_type": cpu_type,
        "host_cpu_cores_min": host_cpu_cores_min,
        "host_ram_gb_min": host_ram_gb_min,
        "gpu_interconnect": gpu_interconnect,
        "datacenter_grade": datacenter_grade,
        "static_ip": static_ip,
    }
    for key, val in spec_filters.items():
        if val is None:
            continue
        query_params[key] = str(val).lower() if isinstance(val, bool) else val
    params = urllib.parse.urlencode(query_params)
    url = f"{base_url}/listings?{params}"

    payload = _fetch_json(url)

    items = payload.get("items", [])
    console = Console()
    table = Table(title="Open Listings", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Listing ID", style="bold", overflow="fold")
    table.add_column("Agent ID")
    table.add_column("Seller")
    table.add_column("Buyer")
    table.add_column("Offer")
    table.add_column("Demand")
    table.add_column("Created", justify="right")

    for row in items:
        offer_display = _format_resource(row.get("offer_resource", {}))
        demand_display = _format_resource(row.get("demand_resource", {}))
        table.add_row(
            str(row.get("listing_id", "-")),
            _shorten(str(row.get("agent_id", "-")), 32),
            _shorten(str(row.get("seller", "-")), 40),
            _shorten(str(row.get("buyer", "-")), 40),
            offer_display if "\n" in offer_display else _shorten(offer_display, 120),
            demand_display if "\n" in demand_display else _shorten(demand_display, 120),
            _short_ts(row.get("created_at")),
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
    registry_url: str = typer.Option(
        None,
        "--registry-url",
        "-r",
        help="Registry indexer base URL (config.toml: registry.url).",
    ),
) -> None:
    """Show a single listing by ID, fetched from the registry indexer."""
    base_url = (
        registry_url
        or resolve_config_value(toml_path="registry.url")
        or "http://localhost:8080"
    )
    base_url = _normalize_registry_url(base_url)
    url = f"{base_url}/listings/{listing_id}"
    payload = _fetch_json(url)
    found = payload.get("listing", payload)

    console = Console()
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    table.add_row("Listing ID", str(found.get("listing_id", "-")))
    table.add_row("Agent ID", str(found.get("agent_id", "-")))
    table.add_row("Status", str(found.get("status", "-")))
    table.add_row("Seller", str(found.get("seller", "-")))
    table.add_row("Buyer", str(found.get("buyer", "-")))
    max_secs = found.get("max_duration_seconds")
    table.add_row(
        "Max duration (s)",
        str(max_secs) if max_secs else "unlimited",
    )
    table.add_row("Created", _short_ts(found.get("created_at")))
    table.add_row("Updated", _short_ts(found.get("updated_at")))
    table.add_row("Offer", _format_resource(found.get("offer_resource", {})))
    table.add_row("Demand", _format_resource(found.get("demand_resource", {})))

    console.print(Panel(table, title="Marketplace Listing", border_style="blue"))
