from __future__ import annotations

import os
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import typer
import json
import urllib.parse

from .common import REPO_ROOT, run_step
from .groups.order import order_app
from .groups.registry import registry_app
from .groups.network import network_app
from .groups.config import config_app
from .groups.dev import dev_app
from .groups.agent import agent_app

from market.helpers import (
    REPO_ROOT,
    _fetch_json,
    _format_resource,
    _format_resource_full,
    _normalize_registry_resource,
    _normalize_registry_url,
    _post_json,
    _resolve_agent_url,
    _short_ts,
    _shorten,
)
from market.groups.agent import agent_app

from market.helpers import (
    REPO_ROOT,
    _fetch_json,
    _format_resource,
    _format_resource_full,
    _normalize_registry_resource,
    _normalize_registry_url,
    _post_json,
    _resolve_agent_url,
    _short_ts,
    _shorten,
)
from market.groups.agent import agent_app

app = typer.Typer(no_args_is_help=True)


def version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        try:
            __version__ = version("market-cli")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"Market CLI version {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version_flag: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Market CLI - Unified interface for Arkhai market operations."""
    pass


@app.command()
def install(
    with_zerotier: bool = typer.Option(
        False,
        "--with-zerotier",
        help="Install ZeroTier (runs 'make install' in infra, requires sudo).",
    ),
) -> None:
    """Install dependencies for Agent and Registry.\nWith the --with-zerotier flag, also installs ZeroTier."""
    steps: list[tuple[str, list[str], Path]] = [
        (
            "Agent dependencies (uv sync)",
            ["make", "install"],
            REPO_ROOT / "agent",
        ),
        (
            "Registry dependencies (uv sync)",
            ["make", "install"],
            REPO_ROOT / "erc-8004-registry-py",
        ),
        (
            "Contracts dependencies (npm install)",
            ["npm", "install"],
            REPO_ROOT / "erc-8004-contracts",
        ),
    ]

    if with_zerotier:
        steps.append(
            (
                "ZeroTier install (requires sudo)",
                ["make", "install"],
                REPO_ROOT / "infra",
            )
        )

    for label, cmd, cwd in steps:
        run_step(label, cmd, cwd)

    typer.echo("Done.")


@app.command()
def register(
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file passed as ENV_FILE to make register.",
    ),
) -> None:
    """Register agent on-chain (make register)."""
    cmd = ["make", "register"]
    if env:
        cmd.append(f"ENV_FILE={env}")
    run_step(
        "Register agent (make register)",
        cmd,
        REPO_ROOT / "agent",
    )


@app.command()
def start(
    env: str | None = typer.Option(
        None,
        "--env",
        "-e",
        help="Path to env file passed as ENV_FILE to make serve-a2a.",
    ),
) -> None:
    """Start Agent service."""
    cmd = ["make", "serve-a2a"]
    if env:
        cmd.append(f"ENV_FILE={env}")
    run_step(
        "Start agent (make serve-a2a)",
        cmd,
        REPO_ROOT / "agent",
    )

@app.command()
def attestation(
    uid: str = typer.Argument(..., help="Attestation UID (0x-prefixed hex)."),
    agent_url: str | None = typer.Option(
        None,
        "--agent-url",
        "-a",
        help="Agent base URL (env: AGENT_URL or BASE_URL_OVERRIDE).",
    ),
) -> None:
    """Look up an on-chain attestation by UID via the agent's Alkahest client."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    base_url = _resolve_agent_url(agent_url)
    data = _fetch_json(f"{base_url}/attestations/{uid}")

    if data.get("error"):
        typer.secho(f"Error: {data['error']}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)

    console = Console()

    # --- Core attestation fields ---
    from datetime import datetime, timezone

    time_val = data.get("time")
    time_display = (
        datetime.fromtimestamp(time_val, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if isinstance(time_val, (int, float)) and time_val > 0
        else str(time_val)
    )

    is_valid = data.get("is_valid")
    valid_display = "[green]Yes[/green]" if is_valid else "[red]No[/red]"
    is_revoked = data.get("is_revoked")
    revoked_display = "[red]Yes[/red]" if is_revoked else "[green]No[/green]"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column()
    grid.add_row("UID", str(data.get("uid", "-")))
    grid.add_row("Schema", str(data.get("schema", "-")))
    grid.add_row("Attester", str(data.get("attester", "-")))
    grid.add_row("Recipient", str(data.get("recipient", "-")))
    grid.add_row("Ref UID", str(data.get("ref_uid", "-")))
    grid.add_row("Time", time_display)
    grid.add_row("Valid", valid_display)
    grid.add_row("Revoked", revoked_display)
    grid.add_row("Revocable", str(data.get("revocable", "-")))
    grid.add_row("Expiration", str(data.get("expiration_time", "-")))
    console.print(Panel(grid, title="Attestation", border_style="blue"))

    # --- Decoded data panels ---
    obligation = data.get("obligation_data")
    if obligation:
        console.print(Panel(str(obligation), title="Obligation Data (Fulfillment)", border_style="green"))

    demand = data.get("demand_data")
    if demand:
        console.print(Panel(str(demand), title="Demand Data (Lease Terms)", border_style="cyan"))

    # Raw data hex (truncated if long)
    data_hex = data.get("data_hex", "")
    if data_hex and not obligation and not demand:
        display = data_hex[:200] + "..." if len(data_hex) > 200 else data_hex
        console.print(Panel(display, title="Raw Data (hex)", border_style="dim"))


app.add_typer(agent_app, name="agent", help="Query a running agent's local API (orders, decisions).")
app.add_typer(order_app, name="order", help="Manage orders (see subcommands).")
app.add_typer(agent_app, name="agent", help="Inspect agent orders, negotiation threads, and decisions.")
app.add_typer(
    config_app,
    name="config",
    help="Manage market config (targets: agent, provisioning, registry, zerotier).",
)
app.add_typer(network_app, name="network", help="Manage ZeroTier network, mainly for market admins (see subcommands).")
app.add_typer(registry_app, name="registry", help="As Market Admin, manage the Registry Indexer server.")
app.add_typer(dev_app, name="dev", help="Developer utilities (local chain and contract deploy).")


if __name__ == "__main__":
    app()
