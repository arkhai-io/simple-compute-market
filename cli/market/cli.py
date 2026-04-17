from __future__ import annotations

from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

import typer

from .common import REPO_ROOT, DEFAULT_AGENT_ENV, read_env_value, container_db_to_host, run_step
from .groups.order import order_app
from .groups.registry import registry_app
from .groups.network import network_app
from .groups.config import config_app
from .groups.dev import dev_app
from .groups.portfolio import portfolio_app
from .groups.policy import policy_app
from .groups.logs import logs_app

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
    agent_mode = read_env_value(env or DEFAULT_AGENT_ENV, "AGENT_MODE", default="host")
    if agent_mode == "container":
        typer.echo("Agent is running as a container — registration is handled automatically at startup. Nothing to do.")
        return
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
        help="Path to env file. For host mode, passed as ENV_FILE to make serve-a2a. For container mode, passed as --env-file to docker run.",
    ),
    detach: bool = typer.Option(
        False,
        "--detach",
        "-d",
        help="Run container in the background (container mode only).",
    ),
    name: str | None = typer.Option(
        None,
        "--container-name",
        help="Container name (container mode only). Defaults to AGENT_ID from env file.",
    ),
    network: str | None = typer.Option(
        None,
        "--network",
        help="Docker network to join (container mode only). Defaults to DOCKER_NETWORK from env file.",
    ),
) -> None:
    """Start Agent service."""
    agent_mode = read_env_value(env or DEFAULT_AGENT_ENV, "AGENT_MODE", default="host")
    if agent_mode == "container":
        port = read_env_value(env, "PORT", default="8000")
        db_path = read_env_value(env, "AGENT_DB_PATH", default="")
        agent_id = name or read_env_value(env, "AGENT_ID", default="")
        env_abs = str(Path(env).resolve())
        docker_network = network or read_env_value(env, "DOCKER_NETWORK", default="")
        volume_flags: list[str] = []
        if db_path:
            host_data_dir = str(container_db_to_host(db_path).parent)
            rel = db_path[len("/app/"):] if db_path.startswith("/app/") else db_path.lstrip("./")
            container_data_dir = "/app/" + str(Path(rel).parent)
            volume_flags = ["-v", f"{host_data_dir}:{container_data_dir}"]
        network_flags = ["--network", docker_network] if docker_network else []
        name_flags = ["--name", agent_id] if agent_id else []
        detach_flags = ["-d"] if detach else []
        cmd = [
            "docker", "run", "--rm",
            *detach_flags,
            *name_flags,
            "--platform", "linux/amd64",  # image is built for linux/amd64; needed on ARM hosts
            "--env-file", env_abs,
            "-p", f"{port}:{port}",
            "--cap-add", "NET_ADMIN",     # ZeroTier needs to create/configure a virtual network interface
            "--cap-add", "SYS_MODULE",    # ZeroTier may need to load the tun kernel module
            "--device", "/dev/net/tun",   # exposes the host TUN/TAP device so ZeroTier can create its interface
            *volume_flags,
            *network_flags,
            "arkhai:core",
        ]
        run_step("Start agent (docker run arkhai:core)", cmd, REPO_ROOT)
        return
    container_only = [f for f, v in [("--detach", detach), ("--container-name", name), ("--network", network)] if v]
    if container_only:
        typer.echo(f"{', '.join(container_only)} ignored (only applies to container mode).")
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
app.add_typer(policy_app, name="policy", help="RL policy lifecycle: train, eval, export.")
app.add_typer(logs_app, name="logs", help="Inspect stage events and deal status.")

if __name__ == "__main__":
    app()
