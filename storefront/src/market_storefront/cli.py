"""Storefront admin CLI — `market-storefront` console script.

Provider-side commands for managing a running storefront. Buyer
operations live in market-buyer (`market` console script). The two
ship as separate wheels; install both if you both buy and sell.

Subcommands:
    register     Register agent on-chain (one-shot, before `serve`).
    serve        Run the storefront HTTP server in-process.
    publish      Post listings from the agent DB. Mirror of
                 `market buy` on the buyer side.
    escrow       Seller-side escrow lifecycle (claim, refund, show).
    portfolio    Manage local resource portfolio data.
    network      Join the operator's ZeroTier network and list peers.
    config       Inspect or edit the user config.toml.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

import typer

from .cli_logs import logs_app
from .cli_portfolio import portfolio_app
from .cli_publish import register as register_publish_command
from .groups.config import config_app
from .groups.escrow import escrow_app
from .groups.network import network_app


app = typer.Typer(no_args_is_help=True)


def version_callback(value: bool) -> None:
    if value:
        try:
            __version__ = version("market-storefront")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"market-storefront version {__version__}")
        raise typer.Exit()


def _config_path_callback(value: str | None) -> str | None:
    """Override the TOML loader path before any subcommand body runs."""
    if value:
        from service.config_loader import set_user_config_path
        set_user_config_path(Path(value))
    return value


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
    config_file: str | None = typer.Option(
        None,
        "--config",
        callback=_config_path_callback,
        is_eager=True,
        help="Path to an explicit config.toml. Defaults to "
             "$XDG_CONFIG_HOME/arkhai/config.toml.",
    ),
) -> None:
    """market-storefront — provider-side admin CLI."""
    pass


# ---------------------------------------------------------------------------
# register — one-shot on-chain registration
# ---------------------------------------------------------------------------


@app.command("register")
def register_cmd(
    chain_id: int = typer.Option(
        1337, "--chain-id",
        help="Numeric chain ID for canonical-id construction "
             "(default 1337 for the local Anvil stack).",
    ),
) -> None:
    """Register the storefront on-chain via ERC-8004.

    Inputs come from config.toml (TOML-only — no env vars or .env
    files). Run this before `market-storefront serve` on a fresh
    deployment; idempotent on subsequent runs.
    """
    from .commands.register import run_register

    raise typer.Exit(asyncio.run(run_register(chain_id=chain_id)))


# ---------------------------------------------------------------------------
# serve — run the storefront HTTP server in-process
# ---------------------------------------------------------------------------


@app.command("serve")
def serve_cmd(
    host: str = typer.Option(
        "0.0.0.0", "--host",
        help="Bind interface (default 0.0.0.0).",
    ),
    port: int | None = typer.Option(
        None, "--port",
        help="Override seller.port from config.toml.",
    ),
    no_publish: bool = typer.Option(
        False, "--no-publish",
        help="Don't auto-run the publish watch loop alongside the server. "
             "Use for read-only deployments or when running publish in a separate process.",
    ),
    poll_interval: float = typer.Option(
        30.0, "--publish-poll-interval",
        help="Seconds between publish cycles (when auto-publish is enabled).",
    ),
) -> None:
    """Run the storefront HTTP server (uvicorn, foreground).

    Auto-publishes available compute inventory in a background thread by
    default. Pass --no-publish to disable. Listings advertise an optional
    max_duration_seconds ceiling (per-row CSV / [seller.pricing] default);
    buyers supply the actual duration at negotiation init.
    """
    from .commands.serve import run_serve

    run_serve(
        host=host, port=port,
        no_publish=no_publish,
        poll_interval=poll_interval,
    )


# ---------------------------------------------------------------------------
# Group registrations
# ---------------------------------------------------------------------------

app.add_typer(logs_app, name="logs", help="Inspect storefront stage events from the local SQLite log.")
app.add_typer(network_app, name="network", help="Join the operator's ZeroTier network and list peers.")
app.add_typer(portfolio_app, name="portfolio", help="Manage local resource portfolio data.")
app.add_typer(config_app, name="config", help="Inspect or edit the user config.toml (path/show/get/set/init-user).")
app.add_typer(escrow_app, name="escrow", help="Seller-side escrow lifecycle (claim, refund).")
register_publish_command(app)


if __name__ == "__main__":
    app()
