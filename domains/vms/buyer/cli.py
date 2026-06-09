from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import typer

from market_buyer.groups.chain import chain_app
from market_buyer.groups.network import network_app

from . import buy_cli as buy_module
from .config_cli import config_app
from .logs_cli import logs_app
from . import negotiate_cli as negotiate_module
from . import settle_cli as settle_module
from .escrow_cli import escrow_app
from .listing_cli import listing_app


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
    """Set an explicit buyer config path before command bodies run."""
    if value:
        from market_config.config_loader import set_user_config_path

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
        help="Path to an explicit buyer.toml. Defaults to "
        "$XDG_CONFIG_HOME/arkhai/buyer.toml.",
    ),
) -> None:
    """VM buyer CLI for Arkhai market operations."""
    pass


app.add_typer(listing_app, name="listing", help="Browse marketplace listings (list/show).")
app.add_typer(
    config_app,
    name="config",
    help="Inspect or edit the buyer.toml (path/show/get/set/init-user).",
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
