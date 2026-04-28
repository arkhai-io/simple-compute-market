from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError

import typer

from .groups.order import order_app
from .groups.config import config_app
from .groups.dev import dev_app
from .groups.logs import logs_app
from .groups import buy as buy_module
from .groups import negotiate as negotiate_module


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

app.add_typer(order_app, name="order", help="Manage orders (see subcommands).")
app.add_typer(
    config_app,
    name="config",
    help="Manage market config (targets: agent, provisioning, registry, zerotier).",
)
app.add_typer(dev_app, name="dev", help="Developer utilities (local chain + contract deploy).")
app.add_typer(logs_app, name="logs", help="Inspect past buy/negotiate runs (run-log JSONL files).")

buy_module.register(app)
negotiate_module.register(app)


if __name__ == "__main__":
    app()
