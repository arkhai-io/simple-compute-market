from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

app = typer.Typer(no_args_is_help=True)
order_app = typer.Typer(no_args_is_help=True)
network_app = typer.Typer(no_args_is_help=True)

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_step(label: str, cmd: list[str], cwd: Path) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    subprocess.run(cmd, cwd=cwd, check=True, env=env)


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

@order_app.command("create")
def order_create() -> None:
    """Create a new order (stub)."""
    typer.echo("Not implemented: order create")


@order_app.command("update")
def order_update() -> None:
    """Update an existing order (stub)."""
    typer.echo("Not implemented: order update")


@order_app.command("cancel")
def order_cancel() -> None:
    """Cancel an order (stub)."""
    typer.echo("Not implemented: order cancel")


@order_app.command("history")
def order_history() -> None:
    """Show order history (stub)."""
    typer.echo("Not implemented: order history")

@order_app.command("list")
def order_list() -> None:
    """List orders (stub)."""
    typer.echo("Not implemented: order list")


@order_app.command("show")
def order_show(order_id: str = typer.Argument(..., help="Order ID")) -> None:
    """Show an order (stub)."""
    typer.echo(f"Not implemented: order show {order_id}")


app.add_typer(order_app, name="order", help="Manage orders (see subcommands).")

@app.command()
def register() -> None:
    """Register (stub)."""
    typer.echo("Not implemented: register")


@app.command()
def start() -> None:
    """Start services (stub)."""
    typer.echo("Not implemented: start")


@app.command()
def config() -> None:
    """Manage config (stub)."""
    typer.echo("Not implemented: config")


@network_app.command("init")
def network_init() -> None:
    """Initialize network (stub)."""
    typer.echo("Not implemented: network init")


@network_app.command("create")
def network_create() -> None:
    """Create network (stub)."""
    typer.echo("Not implemented: network create")


@network_app.command("add")
def network_add(member_id: str = typer.Argument(..., help="Member ID")) -> None:
    """Authorize a member (stub)."""
    typer.echo(f"Not implemented: network add {member_id}")


@network_app.command("get-peers")
def network_get_peers() -> None:
    """Get network peers (stub)."""
    typer.echo("Not implemented: network get-peers")


app.add_typer(network_app, name="network", help="Manage ZeroTier network, mainly for market admins (see subcommands).")


if __name__ == "__main__":
    app()
