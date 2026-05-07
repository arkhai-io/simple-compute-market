from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import typer

from .groups.chain import chain_app
from .groups.listing import listing_app
from .groups.config import config_app
from .groups.logs import logs_app
from .groups.escrow import escrow_app
from .groups.network import network_app
from .groups import buy as buy_module
from .groups import negotiate as negotiate_module
from .groups import settle as settle_module


app = typer.Typer(no_args_is_help=True)


def version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        try:
            __version__ = version("market-buyer")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"market-buyer version {__version__}")
        raise typer.Exit()


def _config_path_callback(value: str | None) -> str | None:
    """Point the TOML loader at an explicit path before any subcommand
    body runs. Default (no flag) leaves the XDG location in effect."""
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
    """market — buyer-side CLI for Arkhai market operations.

    Pure HTTP client. No server, no agent runtime, no database.

    Provider-side commands (start a storefront, register on-chain,
    publish offers, manage policy, etc.) live in the separate
    `market-storefront` package; install both if you both buy and
    sell.
    """
    pass


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

app.add_typer(listing_app, name="listing", help="Browse marketplace listings (list/show).")
app.add_typer(
    config_app,
    name="config",
    help="Inspect or edit the user config.toml (path/show/get/set/init-user).",
)
app.add_typer(logs_app, name="logs", help="Inspect past buy/negotiate runs (run-log JSONL files).")
app.add_typer(escrow_app, name="escrow", help="Buyer-side escrow lifecycle (create, reclaim).")
app.add_typer(network_app, name="network", help="Join the operator's ZeroTier network and list peers.")
app.add_typer(chain_app, name="chain", help="Sanity-check chain config (eth_getCode against configured addresses).")

buy_module.register(app)
negotiate_module.register(app)
settle_module.register(app)


if __name__ == "__main__":
    app()
