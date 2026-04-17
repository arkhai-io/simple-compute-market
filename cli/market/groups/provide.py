"""Top-level `market provide` command.

The seller's counterpart to `market buy`. Wraps the seller's start-of-day
flow behind a single command:

  1. (optional) Import a CSV of compute resources into the agent DB.
  2. Read the DB for `state='available'` compute rows.
  3. POST /orders/create on the agent, once per resource, offering the
     compute and demanding the configured token amount.
  4. Print a table of published orders.

Assumes the seller agent is already running (mirror of `market buy`).
Assumes one order per available resource row (V1 strategy); a future
`--watch` flag can add continuous re-publish after lease end.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from ..common import REPO_ROOT, read_env_value
from .order import (
    _get_auth_headers,
    _normalize_registry_url,
    _post_json,
)
from .logs import _resolve_db_path


def _import_csv(csv_path: str, env: Optional[str], db: Optional[str]) -> None:
    """Invoke the existing import_resources_csv.py script directly.

    Uses `core/.venv/bin/python` rather than `uv run` — the latter fails
    cleanly from outside the core project, and the core venv is a stable
    dependency of the seller-side deployment anyway.
    """
    script = REPO_ROOT / "core" / "agent" / "scripts" / "import_resources_csv.py"
    python = REPO_ROOT / "core" / ".venv" / "bin" / "python"
    if not python.exists():
        raise typer.BadParameter(
            f"Core venv not found at {python}. "
            "Run `market install` (or `cd core && uv sync`) first."
        )
    cmd = [
        str(python), str(script),
        "--csv", str(Path(csv_path).resolve()),
    ]
    if db:
        cmd.extend(["--db-path", str(Path(db).resolve())])
    if env:
        cmd.extend(["--env-file", str(Path(env).resolve())])
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def _available_resources(db_path: str) -> list[dict]:
    """Read all `state='available'` compute resources from the agent DB."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT resource_id, resource_subtype, unit, value, state, attributes
               FROM resources
               WHERE resource_type = 'compute.gpu' AND state = 'available'
               ORDER BY resource_id""",
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        try:
            attrs = json.loads(row["attributes"] or "{}")
        except json.JSONDecodeError:
            attrs = {}
        out.append({
            "resource_id": row["resource_id"],
            "gpu_model": attrs.get("gpu_model"),
            "quantity": int(row["value"]) if row["value"] is not None else 1,
            "sla": attrs.get("sla", 0.0),
            "region": attrs.get("region"),
        })
    return out


def _publish_offer(
    agent_url: str,
    offer: dict,
    demand: dict,
    duration_hours: int,
    wallet_address: str,
    private_key: Optional[str],
) -> dict:
    """POST /orders/create and return the full response dict."""
    url = f"{_normalize_registry_url(agent_url)}/orders/create"
    payload = {"offer": offer, "demand": demand, "duration_hours": duration_hours}
    headers = _get_auth_headers("create_order", wallet_address, private_key)
    return _post_json(url, payload, headers)


def register(app: typer.Typer) -> None:
    """Register the top-level `market provide` command."""

    @app.command("provide")
    def provide(
        inventory: Optional[str] = typer.Option(
            None, "--inventory", "-i",
            help="Path to a CSV file describing compute resources to import before publishing.",
        ),
        min_price: str = typer.Option(
            ..., "--min-price", "-p",
            help="Minimum price per order, in human units of --token.",
        ),
        token: str = typer.Option("MOCK", "--token", help="Payment token symbol."),
        duration_hours: int = typer.Option(
            1, "--duration-hours", "-t",
            help="Lease duration offered per order (hours).",
        ),
        agent_url: Optional[str] = typer.Option(
            None, "--agent-url", "-a",
            help="Seller agent base URL (env: AGENT_URL, BASE_URL_OVERRIDE).",
        ),
        env: Optional[str] = typer.Option(
            None, "--env", "-e",
            help="Env file (reads BASE_URL_OVERRIDE, AGENT_PRIV_KEY, AGENT_WALLET_ADDRESS, AGENT_DB_PATH).",
        ),
        db: Optional[str] = typer.Option(
            None, "--db", help="Explicit seller agent SQLite DB path.",
        ),
    ) -> None:
        """Publish sell orders for every available compute resource on the seller's node."""
        console = Console()
        env_path = Path(env) if env else None

        base_url = (
            agent_url
            or (read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None)
            or os.getenv("AGENT_URL")
            or os.getenv("BASE_URL_OVERRIDE")
            or "http://localhost:8001"
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
        db_path = _resolve_db_path(db, env)
        if not db_path:
            typer.secho(
                "Could not resolve seller agent DB. Pass --db or --env with AGENT_DB_PATH set.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        if inventory:
            csv_file = Path(inventory)
            if not csv_file.exists():
                raise typer.BadParameter(f"Inventory file not found: {inventory}")
            console.print(f"[bold]Importing inventory:[/bold] {csv_file}")
            try:
                _import_csv(str(csv_file), env, db)
            except subprocess.CalledProcessError as exc:
                typer.secho(f"Inventory import failed: {exc}", err=True, fg=typer.colors.RED)
                raise typer.Exit(2)

        resources = _available_resources(db_path)
        if not resources:
            console.print(
                "[yellow]No available compute resources in the agent DB.[/yellow] "
                "Pass --inventory <csv> or seed the DB first.",
            )
            raise typer.Exit(3)

        demand = {"token": token, "amount": min_price}
        published: list[dict] = []
        failed: list[tuple[dict, str]] = []
        for res in resources:
            offer = {
                "gpu_model": res["gpu_model"],
                "quantity": res["quantity"],
                "sla": res["sla"],
                "region": res["region"],
            }
            try:
                resp = _publish_offer(
                    base_url, offer, demand, duration_hours, wallet_address, private_key,
                )
                published.append({"resource": res, "response": resp})
            except typer.Exit:
                # _post_json already logged the error
                failed.append((res, "HTTP error (see above)"))
            except Exception as exc:
                failed.append((res, str(exc)))

        summary = Table(title="Published offers", box=box.SIMPLE_HEAVY, expand=True)
        summary.add_column("Resource", style="bold")
        summary.add_column("GPU")
        summary.add_column("Region")
        summary.add_column("Order ID", overflow="fold")
        summary.add_column("Status")
        for entry in published:
            res = entry["resource"]
            resp = entry["response"]
            summary.add_row(
                res["resource_id"],
                f"{res['gpu_model']} x{res['quantity']}",
                res["region"] or "-",
                str(resp.get("order_id", "-")),
                str(resp.get("status", "-")),
            )
        for res, reason in failed:
            summary.add_row(
                res["resource_id"],
                f"{res['gpu_model']} x{res['quantity']}",
                res["region"] or "-",
                "-",
                f"[red]failed: {reason}[/red]",
            )
        console.print(summary)

        totals = Table.grid(padding=(0, 2))
        totals.add_column(style="bold")
        totals.add_column()
        totals.add_row("Published", str(len(published)))
        totals.add_row("Failed", str(len(failed)))
        totals.add_row("Agent", base_url)
        totals.add_row("Demand per order", f"{min_price} {token}")
        console.print(Panel(totals, title="Summary", border_style="green" if not failed else "yellow"))

        if failed and not published:
            raise typer.Exit(4)
