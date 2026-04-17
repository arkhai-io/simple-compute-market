"""Top-level `market buy` command.

Wraps the full buyer pipeline behind a single synchronous CLI call:
  1. POST /orders/create with {offer: token, demand: compute}
  2. Poll DB-derived stage until closed / post_settlement / failure / timeout
  3. Print credentials

Assumes the buyer agent is already running (same as `order create`).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from ..common import read_env_value
from .logs import _derive_stage, _resolve_db_path
from .order import (
    _get_auth_headers,
    _normalize_registry_url,
    _post_json,
    _print_credentials_table,
    _resolve_db_path as _order_resolve_db_path,
)


TERMINAL_STAGES = {"closed"}
READY_STAGES = {"post_settlement", "closed"}


def _build_resources(
    gpu: Optional[str],
    quantity: int,
    sla: Optional[float],
    region: Optional[str],
    max_price: str,
    token: str,
    demand_json: Optional[str],
    offer_json: Optional[str],
) -> tuple[dict, dict]:
    """Build (offer, demand) resource dicts for the /orders/create payload.

    Buyer semantics: offer = token (what they pay), demand = compute (what they want).
    """
    if demand_json:
        demand = json.loads(demand_json)
    else:
        if not gpu:
            raise typer.BadParameter("--gpu is required (or pass --demand-json)")
        demand = {"gpu_model": gpu, "quantity": quantity}
        if sla is not None:
            demand["sla"] = sla
        if region:
            demand["region"] = region

    if offer_json:
        offer = json.loads(offer_json)
    else:
        offer = {"token": token, "amount": max_price}

    return offer, demand


def _find_order_negotiation(conn: sqlite3.Connection, order_id: str) -> Optional[str]:
    """Return the negotiation_id associated with a local order, if one exists yet."""
    row = conn.execute(
        """SELECT negotiation_id FROM negotiation_threads
           WHERE our_order_id = ? OR their_order_id = ?
           ORDER BY created_at DESC LIMIT 1""",
        (order_id, order_id),
    ).fetchone()
    return row[0] if row else None


def _credentials_present(conn: sqlite3.Connection, order_id: str) -> bool:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM credentials WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        return bool(row and row[0])
    except sqlite3.OperationalError:
        return False


def _poll_snapshot(db_path: str, order_id: str) -> dict:
    """Single read: returns {stage, detail, negotiation_id, credentials_ready}.

    Opens the DB read-only with nolock=1 so a busy writer on the other side
    (e.g. the agent doing WAL checkpoints) does not surface as a spurious
    'attempt to write a readonly database'. Retries briefly on transient I/O.
    """
    last_err: Exception | None = None
    for _ in range(5):
        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5,
            )
            conn.row_factory = sqlite3.Row
            try:
                nid = _find_order_negotiation(conn, order_id)
                creds_ready = _credentials_present(conn, order_id)
                if not nid:
                    return {
                        "stage": "discovery",
                        "detail": "matching seller",
                        "negotiation_id": None,
                        "credentials_ready": creds_ready,
                    }
                info = _derive_stage(conn, nid)
                info["credentials_ready"] = creds_ready
                info["negotiation_id"] = nid
                return info
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            last_err = exc
            time.sleep(0.2)
    # Final attempt failed — surface a snapshot that represents "we can't read".
    return {
        "stage": "unknown",
        "detail": f"db read error: {last_err}",
        "negotiation_id": None,
        "credentials_ready": False,
    }


def _create_buy_order(
    agent_url: str,
    offer: dict,
    demand: dict,
    duration_hours: int,
    wallet_address: str,
    private_key: Optional[str],
) -> str:
    """POST /orders/create and return the new order_id."""
    payload = {"offer": offer, "demand": demand, "duration_hours": duration_hours}
    url = f"{_normalize_registry_url(agent_url)}/orders/create"
    headers = _get_auth_headers("create_order", wallet_address, private_key)
    response = _post_json(url, payload, headers)
    order_id = response.get("order_id")
    if not order_id:
        raise typer.BadParameter(f"Agent did not return order_id: {response}")
    return order_id


def _wait_for_completion(
    db_path: str,
    order_id: str,
    timeout: int,
    poll_interval: float,
    console: Console,
) -> dict:
    """Block until credentials ready / closed / failure / timeout. Returns final snapshot."""
    deadline = time.time() + timeout

    def render(info: dict) -> Panel:
        color = {
            "discovery": "blue",
            "negotiation": "yellow",
            "settlement": "green",
            "provision": "cyan",
            "post_settlement": "magenta",
            "closed": "bold green",
            "unknown": "red",
        }.get(info.get("stage", ""), "white")
        lines = [f"[bold]Order:[/bold] {order_id}"]
        lines.append(f"[bold]Stage:[/bold] [{color}]{info.get('stage', '?')}[/{color}]")
        if info.get("detail"):
            lines.append(f"[bold]Detail:[/bold] {info['detail']}")
        for key in ("negotiation_id", "escrow_uid", "rounds"):
            val = info.get(key)
            if val is not None:
                lines.append(f"[dim]{key}:[/dim] {val}")
        lines.append(f"[dim]timeout in {max(0, int(deadline - time.time()))}s[/dim]")
        return Panel("\n".join(lines), title="[bold]market buy[/bold]", border_style=color)

    with Live(console=console, refresh_per_second=2) as live:
        while True:
            info = _poll_snapshot(db_path, order_id)
            live.update(render(info))

            if info.get("credentials_ready") or info.get("stage") in READY_STAGES:
                return info
            if info.get("terminal_state") in ("failure", "superseded"):
                return info
            if time.time() >= deadline:
                info["_timed_out"] = True
                return info
            time.sleep(poll_interval)


def register(app: typer.Typer) -> None:
    """Register the top-level `market buy` command on the given Typer app."""

    @app.command("buy")
    def buy(
        gpu: Optional[str] = typer.Option(None, "--gpu", "-g", help="GPU model, e.g. 'RTX 5080'."),
        quantity: int = typer.Option(1, "--quantity", "-q", help="Number of GPUs."),
        sla: Optional[float] = typer.Option(None, "--sla", help="Minimum SLA percentage."),
        region: Optional[str] = typer.Option(None, "--region", help="Preferred region."),
        max_price: str = typer.Option(..., "--max-price", "-p", help="Price ceiling (human units of --token)."),
        token: str = typer.Option("MOCK", "--token", help="Payment token symbol."),
        duration_hours: int = typer.Option(1, "--duration-hours", "-t", help="Lease duration in hours."),
        demand_json: Optional[str] = typer.Option(None, "--demand-json", help="Raw demand resource JSON (overrides --gpu/--quantity/--sla/--region)."),
        offer_json: Optional[str] = typer.Option(None, "--offer-json", help="Raw offer resource JSON (overrides --max-price/--token)."),
        timeout: int = typer.Option(600, "--timeout", help="Total wait budget in seconds."),
        poll_interval: float = typer.Option(2.0, "--poll-interval", help="Seconds between DB polls."),
        agent_url: Optional[str] = typer.Option(None, "--agent-url", "-a", help="Buyer agent base URL (env: AGENT_URL, BASE_URL_OVERRIDE)."),
        env: Optional[str] = typer.Option(None, "--env", "-e", help="Env file (reads BASE_URL_OVERRIDE, AGENT_PRIV_KEY, AGENT_DB_PATH)."),
        db: Optional[str] = typer.Option(None, "--db", help="Explicit buyer agent SQLite DB path."),
        show_password: bool = typer.Option(False, "--show-password", help="Reveal credential passwords when printing."),
    ) -> None:
        """Buy compute with the given constraints — synchronous, one command."""
        console = Console()
        env_path = Path(env) if env else None

        base_url = (
            agent_url
            or (read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None)
            or os.getenv("AGENT_URL")
            or os.getenv("BASE_URL_OVERRIDE")
            or "http://localhost:8000"
        )
        private_key = (
            (read_env_value(env_path, "AGENT_PRIV_KEY") if env_path else None)
            or os.getenv("AGENT_PRIV_KEY")
        )
        wallet_address = (
            (read_env_value(env_path, "AGENT_WALLET_ADDRESS") if env_path else None)
            or os.getenv("AGENT_WALLET_ADDRESS")
            or ""
        )
        db_path = _resolve_db_path(db, env) or _order_resolve_db_path(db, env)
        if not db_path:
            typer.secho(
                "Could not resolve buyer agent DB. Pass --db or --env with AGENT_DB_PATH set.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        try:
            offer, demand = _build_resources(
                gpu, quantity, sla, region, max_price, token, demand_json, offer_json
            )
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"Invalid JSON: {exc}") from exc

        summary = Table.grid(padding=(0, 2))
        summary.add_column(style="bold")
        summary.add_column()
        summary.add_row("Agent", base_url)
        summary.add_row("Demand", json.dumps(demand, separators=(",", ":")))
        summary.add_row("Offer", json.dumps(offer, separators=(",", ":")))
        summary.add_row("Duration (h)", str(duration_hours))
        console.print(Panel(summary, title="Buy request", border_style="blue"))

        order_id = _create_buy_order(base_url, offer, demand, duration_hours, wallet_address, private_key)
        console.print(f"[green]Order created:[/green] {order_id}")

        final = _wait_for_completion(db_path, order_id, timeout, poll_interval, console)

        if final.get("_timed_out"):
            console.print(f"[red]Timed out after {timeout}s — order is in stage '{final.get('stage')}'.[/red]")
            console.print(f"[dim]Resume with: market logs status {order_id}[/dim]")
            raise typer.Exit(2)
        if final.get("terminal_state") in ("failure", "superseded"):
            console.print(f"[red]Negotiation ended without a deal: {final.get('terminal_state')}[/red]")
            raise typer.Exit(3)

        console.print()
        _print_credentials_table(console, db_path, order_id, show_password=show_password)
