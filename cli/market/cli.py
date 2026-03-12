from __future__ import annotations

from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

import typer

#from .common import run_step
from .groups.order import order_app
from .groups.registry import registry_app
from .groups.network import network_app
from .groups.config import config_app
from .groups.dev import dev_app
from .groups.portfolio import portfolio_app

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

# This functionality needs to be refactored to remove any assumptions this is running in a git repo.
# You cannot import repo root, you cannot call makefile targets, etc.
# You can run a container for the agent or build a wheel of the agent, import the dependency here like I showed for alkahest within the agent, and call it within this standalone executable.
#@app.command()
#def register(
#    env: str | None = typer.Option(
#        None,
#        "--env",
#        "-e",
#        help="Path to env file passed as ENV_FILE to make register.",
#    ),
#) -> None:
#    """Register agent on-chain (make register)."""
#    cmd = ["make", "register"]
#    if env:
#        cmd.append(f"ENV_FILE={env}")
#    run_step(
#        "Register agent (make register)",
#        cmd,
#        REPO_ROOT / "agent",
#    )

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
            REPO_ROOT / "core" / "agent",
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
        REPO_ROOT / "core" / "agent",
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
        REPO_ROOT / "core" / "agent",
    )


app.add_typer(order_app, name="order", help="Manage orders (see subcommands).")
app.add_typer(
    config_app,
    name="config",
    help="Manage market config (targets: agent, provisioning, registry, zerotier).",
)
app.add_typer(network_app, name="network", help="Manage ZeroTier network, mainly for market admins (see subcommands).")
app.add_typer(registry_app, name="registry", help="As Market Admin, manage the Registry Indexer server.")
app.add_typer(portfolio_app, name="portfolio", help="Manage local resource portfolio data.")
app.add_typer(dev_app, name="dev", help="Developer utilities (local chain and contract deploy).")


if __name__ == "__main__":
    app()
