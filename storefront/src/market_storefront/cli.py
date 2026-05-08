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
        None, "--chain-id",
        help="Numeric chain ID for canonical-id construction. "
             "When omitted, queried from chain.rpc_url via eth_chainId; "
             "falls back to 1337 (local Anvil) if no RPC is configured.",
    ),
) -> None:
    """Register the storefront on-chain via ERC-8004.

    Inputs come from config.toml (TOML-only — no env vars or .env
    files). Run this before `market-storefront serve` on a fresh
    deployment; idempotent on subsequent runs.
    """
    from .commands.register import run_register
    from .utils.config import CONFIG

    resolved_chain_id = chain_id
    if resolved_chain_id is None:
        resolved_chain_id = _query_chain_id(CONFIG.chain_rpc_url) or 1337
        typer.echo(f"Using chain_id={resolved_chain_id} (auto-detected).")

    raise typer.Exit(asyncio.run(run_register(chain_id=resolved_chain_id)))


def _query_chain_id(rpc_url: str | None) -> int | None:
    """Query eth_chainId against the configured RPC.

    Returns None on any failure (network, malformed reply, no rpc_url).
    The caller falls back to a default — `register` accepts a wrong
    chain_id more gracefully than a stuck startup, so we prefer "fall
    through with default" over "crash".

    Translates ``ws://`` / ``wss://`` URLs to ``http://`` / ``https://``
    for this one-shot RPC call: urllib doesn't speak websocket, but the
    eth_chainId method is identical over either transport. The seller's
    runtime keeps using the configured ws:// URL for event subscriptions.
    """
    if not rpc_url or not rpc_url.strip():
        return None
    http_url = rpc_url.strip()
    if http_url.startswith("ws://"):
        http_url = "http://" + http_url[len("ws://"):]
    elif http_url.startswith("wss://"):
        http_url = "https://" + http_url[len("wss://"):]
    try:
        import json as _json
        from urllib.request import Request, urlopen
        req = Request(
            http_url,
            data=_json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": [],
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=5) as resp:
            body = _json.loads(resp.read())
        return int(body.get("result", "0x0"), 16) or None
    except Exception as exc:
        typer.secho(
            f"[register] eth_chainId lookup against {rpc_url!r} failed: {exc}",
            err=True, fg=typer.colors.YELLOW,
        )
        return None


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
) -> None:
    """Run the storefront HTTP server (uvicorn, foreground).

    Listings advertise an optional max_duration_seconds ceiling
    (per-row CSV / [seller.pricing] default); buyers supply the actual
    duration at negotiation init.
    """
    from market_storefront.server import run_serve

    run_serve(host=host, port=port)


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
