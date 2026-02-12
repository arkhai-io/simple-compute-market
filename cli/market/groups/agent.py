from __future__ import annotations

import json
import urllib.parse

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from market.cli import _fetch_json, _resolve_agent_url, _short_ts

agent_app = typer.Typer(no_args_is_help=True)


@agent_app.command("orders")
def agent_orders(
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter by status (open, matched, fulfilled, etc.).",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        help="Maximum orders to fetch.",
    ),
    agent_url: str | None = typer.Option(
        None,
        "--agent-url",
        "-a",
        help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """List orders from the running agent API."""
    base_url = _resolve_agent_url(agent_url)
    params: dict[str, str] = {}
    if status:
        params["status"] = status
    if limit:
        params["limit"] = str(limit)
    qs = urllib.parse.urlencode(params)
    url = f"{base_url}/orders" + (f"?{qs}" if qs else "")
    data = _fetch_json(url)
    orders = data.get("orders", [])

    console = Console()
    if not orders:
        console.print("No orders found.")
        return

    table = Table(title="Agent Orders", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Order ID", style="bold", overflow="fold")
    table.add_column("Status")
    table.add_column("Escrow UID")
    table.add_column("Updated", justify="right")

    for o in orders:
        table.add_row(
            str(o.get("order_id", "-")),
            str(o.get("status", "-")),
            str(o.get("escrow_uid") or "-"),
            _short_ts(o.get("updated_at")),
        )

    console.print(table)
    console.print(f"Total: {data.get('total', len(orders))}")


@agent_app.command("order")
def agent_order(
    order_id: str = typer.Argument(..., help="Order ID to look up."),
    agent_url: str | None = typer.Option(
        None,
        "--agent-url",
        "-a",
        help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """Show a single order from the running agent API."""
    base_url = _resolve_agent_url(agent_url)
    url = f"{base_url}/orders/{order_id}"
    data = _fetch_json(url)

    console = Console()
    console.print(Panel(
        json.dumps(data, indent=2, default=str),
        title=f"Order {order_id}",
        border_style="blue",
    ))


@agent_app.command("decisions")
def agent_decisions(
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Maximum decisions to fetch.",
    ),
    event_type: str | None = typer.Option(
        None,
        "--event-type",
        help="Filter by event type.",
    ),
    agent_url: str | None = typer.Option(
        None,
        "--agent-url",
        "-a",
        help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """List recent decisions from the running agent API."""
    base_url = _resolve_agent_url(agent_url)
    params: dict[str, str] = {"limit": str(limit)}
    if event_type:
        params["event_type"] = event_type
    qs = urllib.parse.urlencode(params)
    url = f"{base_url}/decisions?{qs}"
    data = _fetch_json(url)
    decisions = data.get("decisions", [])

    console = Console()
    if not decisions:
        console.print("No decisions found.")
        return

    table = Table(title="Agent Decisions", box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Decision ID", style="bold", overflow="fold")
    table.add_column("Event Type")
    table.add_column("Action")
    table.add_column("Timestamp", justify="right")

    for d in decisions:
        table.add_row(
            str(d.get("decision_id", "-")),
            str(d.get("event_type", "-")),
            str(d.get("action_type", "-")),
            str(d.get("timestamp", "-")),
        )

    console.print(table)
    console.print(f"Total: {data.get('total', len(decisions))}")
