from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

app = typer.Typer(no_args_is_help=True)
order_app = typer.Typer(no_args_is_help=True)
network_app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
dev_app = typer.Typer(no_args_is_help=True)

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
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
def config() -> None:
    """Manage config (stub)."""
    typer.echo("Not implemented: config")


@network_app.command("install")
def network_install() -> None:
    """Install ZeroTier, if it isn't already installed."""
    run_step(
        "ZeroTier install (make install)",
        ["make", "install"],
        REPO_ROOT / "infra",
    )


@network_app.command("create")
def network_create() -> None:
    """Create network."""
    run_step(
        "Create ZeroTier network (make create-network)",
        ["make", "create-network"],
        REPO_ROOT / "infra",
    )


@network_app.command("add")
def network_add(member_id: str = typer.Argument(..., help="Member ID")) -> None:
    """Authorize a member."""
    run_step(
        f"Authorize ZeroTier member {member_id}",
        ["make", "add-node", f"NODE_ID={member_id}"],
        REPO_ROOT / "infra",
    )


@network_app.command("get-peers")
def network_get_peers() -> None:
    """Get network peers."""
    run_step(
        "Get ZeroTier peers (make get-peers)",
        ["make", "get-peers"],
        REPO_ROOT / "infra",
    )


app.add_typer(network_app, name="network", help="Manage ZeroTier network, mainly for market admins (see subcommands).")

@registry_app.command("start")
def registry_start() -> None:
    """Start the registry server."""
    run_step(
        "Start registry (make serve)",
        ["make", "serve"],
        REPO_ROOT / "erc-8004-registry-py",
    )


app.add_typer(registry_app, name="registry", help="As Market Admin, manage the registry server.")

@dev_app.command("test-env")
def dev_test_env() -> None:
    """As a Developer, run the Anvil test env."""
    run_step(
        "Start Anvil test env (make test-env)",
        ["make", "test-env"],
        REPO_ROOT / "agent",
    )


@dev_app.command("deploy-registry")
def dev_deploy_registry(
    rpc_url: str = typer.Option(
        ...,
        "--rpc-url",
        "-r",
        help="RPC URL to deploy against (sets ANVIL_RPC_URL).",
    ),
) -> None:
    """As a Developer, deploy the ERC-8004 to the given RPC_URL."""
    run_step(
        f"Deploy ERC-8004 contracts to {rpc_url}",
        ["npm", "run", "deploy:anvil"],
        REPO_ROOT / "erc-8004-contracts",
        {"ANVIL_RPC_URL": rpc_url},
    )


app.add_typer(dev_app, name="dev", help="Developer utilities (local chain and contract deploy).")


if __name__ == "__main__":
    app()
