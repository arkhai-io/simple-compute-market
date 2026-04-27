from __future__ import annotations

from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

import typer

from .common import REPO_ROOT, DEFAULT_AGENT_ENV, read_env_value, container_db_to_host, run_step
from service.role import ROLE_FILE, clear_role, get_role, set_role
from .groups.order import order_app
from .groups.registry import registry_app
from .groups.network import network_app
from .groups.config import config_app
from .groups.dev import dev_app
from .groups.portfolio import portfolio_app
from .groups.policy import policy_app
from .groups.logs import logs_app
from .groups import buy as buy_module
from .groups import negotiate as negotiate_module
from .groups import provide as provide_module


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
    """Market CLI — Unified interface for Arkhai market operations."""
    pass


# ---------------------------------------------------------------------------
# install — role-specific setup
# ---------------------------------------------------------------------------


_BUYER_ENV_CHECKLIST = [
    "AGENT_WALLET_ADDRESS   # buyer's 0x-prefixed wallet (must be funded with payment token)",
    "AGENT_PRIV_KEY         # private key for signing HTTP requests + creating escrow on-chain",
    "CHAIN_RPC_URL          # e.g. https://sepolia.base.org",
    "CHAIN_NAME             # e.g. ethereum_sepolia | base_sepolia | anvil",
    "INDEXER_URL            # registry indexer endpoint, for /orders queries",
    "ALKAHEST_ADDRESS_CONFIG_PATH  # path to Alkahest address JSON (only for custom chains)",
]


@app.command()
def install(
    seller: bool = typer.Option(
        False,
        "--seller",
        help=(
            "Full install for running a seller agent (adds core/agent, "
            "registry indexer, and contracts on top of the base buyer install)."
        ),
    ),
    with_zerotier: bool = typer.Option(
        False,
        "--with-zerotier",
        help="Install ZeroTier (requires sudo). Only meaningful with --seller.",
    ),
) -> None:
    """Install deps for this role.

    Default (buyer): writes the role marker and prints the env-var
    checklist. No system-level work — the CLI itself has everything a
    pure client needs (HTTP, signing, on-chain escrow via alkahest-py).

    With --seller: runs the agent/registry/contracts installs and marks
    this as a seller install. Subsequent `market --help` shows the full
    command surface.
    """
    if not seller:
        if with_zerotier:
            typer.secho(
                "--with-zerotier only applies to --seller installs; ignoring.",
                err=True, fg=typer.colors.YELLOW,
            )
        marker = set_role("buyer")
        typer.echo("Role: buyer (pure client — no agent, no server).")
        typer.echo(f"Marker: {marker}")
        typer.echo("")
        typer.echo("Required env vars (set in your env or pass via --env to commands):")
        for line in _BUYER_ENV_CHECKLIST:
            typer.echo(f"  {line}")
        typer.echo("")
        typer.echo("Try: market buy --help")
        return

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

    marker = set_role("seller")
    typer.echo("Done.")
    typer.echo(f"Role: seller  ({marker})")


# ---------------------------------------------------------------------------
# role — inspect / reset the current role marker
# ---------------------------------------------------------------------------


@app.command()
def role(
    reset: bool = typer.Option(
        False, "--reset",
        help="Remove the role marker (shows all commands like a fresh checkout).",
    ),
) -> None:
    """Show or reset the current install role."""
    if reset:
        cleared = clear_role()
        if cleared:
            typer.echo(f"Removed role marker at {cleared}.")
        else:
            typer.echo("No role marker was set.")
        return
    current = get_role()
    typer.echo(f"Role: {current}")
    typer.echo(f"Marker file: {ROLE_FILE}{' (not present)' if current == 'unset' else ''}")
    if current == "buyer":
        typer.echo("Seller-only commands are hidden. Run `market install --seller` to switch.")
    elif current == "unset":
        typer.echo("All commands visible. Run `market install` or `market install --seller` to pin a role.")


# ---------------------------------------------------------------------------
# seller-facing commands — only registered when the install is seller (or unset)
# ---------------------------------------------------------------------------


def _register_seller_commands() -> None:
    @app.command("register")
    def register_cmd(
        env: str | None = typer.Option(
            None, "--env", "-e",
            help="Path to env file passed as ENV_FILE to make register.",
        ),
    ) -> None:
        """Register agent on-chain (make register). Seller-only."""
        agent_mode = read_env_value(env or DEFAULT_AGENT_ENV, "AGENT_MODE", default="host")
        if agent_mode == "container":
            typer.echo(
                "Agent is running as a container — registration is handled automatically at startup. "
                "Nothing to do.",
            )
            return
        cmd = ["make", "register"]
        if env:
            cmd.append(f"ENV_FILE={env}")
        run_step("Register agent (make register)", cmd, REPO_ROOT / "core" / "agent")

    @app.command("start")
    def start_cmd(
        env: str | None = typer.Option(
            None, "--env", "-e",
            help="Path to env file. For host mode, passed as ENV_FILE to make serve-a2a. "
                 "For container mode, passed as --env-file to docker run.",
        ),
        detach: bool = typer.Option(
            False, "--detach", "-d",
            help="Run container in the background (container mode only).",
        ),
        name: str | None = typer.Option(
            None, "--container-name",
            help="Container name (container mode only). Defaults to AGENT_ID from env file.",
        ),
        network: str | None = typer.Option(
            None, "--network",
            help="Docker network to join (container mode only). Defaults to DOCKER_NETWORK from env file.",
        ),
    ) -> None:
        """Start the seller agent HTTP server. Seller-only."""
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
                "--platform", "linux/amd64",
                "--env-file", env_abs,
                "-p", f"{port}:{port}",
                "--cap-add", "NET_ADMIN",
                "--cap-add", "SYS_MODULE",
                "--device", "/dev/net/tun",
                *volume_flags,
                *network_flags,
                "arkhai:core",
            ]
            run_step("Start agent (docker run arkhai:core)", cmd, REPO_ROOT)
            return
        container_only = [
            f for f, v in [("--detach", detach), ("--container-name", name), ("--network", network)]
            if v
        ]
        if container_only:
            typer.echo(f"{', '.join(container_only)} ignored (only applies to container mode).")
        cmd = ["make", "serve-a2a"]
        if env:
            cmd.append(f"ENV_FILE={env}")
        run_step("Start agent (make serve-a2a)", cmd, REPO_ROOT / "core" / "agent")

    app.add_typer(network_app, name="network",
                  help="Manage ZeroTier network. Seller/admin only.")
    app.add_typer(registry_app, name="registry",
                  help="Manage the Registry Indexer server. Seller/admin only.")
    app.add_typer(portfolio_app, name="portfolio",
                  help="Manage local resource portfolio data. Seller-only.")
    app.add_typer(policy_app, name="policy",
                  help="RL policy lifecycle: train, eval, export. Seller-only.")
    provide_module.register(app)


# ---------------------------------------------------------------------------
# Shared subcommands — visible to both roles (and in the unset default).
# ---------------------------------------------------------------------------

app.add_typer(order_app, name="order", help="Manage orders (see subcommands).")
app.add_typer(
    config_app,
    name="config",
    help="Manage market config (targets: agent, provisioning, registry, zerotier).",
)
app.add_typer(dev_app, name="dev", help="Developer utilities (local chain + contract deploy).")
app.add_typer(logs_app, name="logs", help="Inspect stage events and deal status.")

buy_module.register(app)
negotiate_module.register(app)


# Role-gated registration: seller-only surface is visible for 'seller' and
# 'unset' (the latter so a fresh checkout sees everything before
# `market install` is run). A buyer install hides it.
if get_role() in ("seller", "unset"):
    _register_seller_commands()


if __name__ == "__main__":
    app()
