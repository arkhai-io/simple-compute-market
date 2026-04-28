"""Storefront admin CLI — `market-storefront` console script.

Provider-side commands for managing a running storefront. Buyer
operations live in market-buyer (`market` console script). The two
ship as separate wheels; install both if you both buy and sell.

Subcommands:
    register     Register agent on-chain (one-shot, before `start`).
    start        Start the storefront HTTP server (host or container).
    provide      Publish offers from the agent DB. Mirror of
                 `market buy` on the buyer side.
    portfolio    Manage local resource portfolio data.
    policy       RL policy lifecycle: train, eval, export.
    network      ZeroTier network admin.
    registry     Off-chain registry indexer admin.
"""

from __future__ import annotations

from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

import typer

from .cli_common import REPO_ROOT, DEFAULT_AGENT_ENV, read_env_value, container_db_to_host, run_step
from .cli_logs import logs_app
from .cli_network import network_app
from .cli_policy import policy_app
from .cli_portfolio import portfolio_app
from .cli_provide import register as register_provide_command
from .cli_registry import registry_app


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
    env: str | None = typer.Option(
        None, "--env", "-e",
        help="Path to env file passed as ENV_FILE to make register.",
    ),
) -> None:
    """Register the storefront on-chain (make register)."""
    agent_mode = read_env_value(env or DEFAULT_AGENT_ENV, "AGENT_MODE", default="host")
    if agent_mode == "container":
        typer.echo(
            "Storefront is running as a container — registration is handled "
            "automatically at startup. Nothing to do.",
        )
        return
    cmd = ["make", "-f", "Makefile.agent", "register"]
    if env:
        cmd.append(f"ENV_FILE={env}")
    run_step("Register storefront (make register)", cmd, REPO_ROOT / "storefront")


# ---------------------------------------------------------------------------
# start — bring up the storefront HTTP server
# ---------------------------------------------------------------------------


@app.command("start")
def start_cmd(
    env: str | None = typer.Option(
        None, "--env", "-e",
        help="Path to env file. For host mode, passed as ENV_FILE to "
             "make serve-a2a. For container mode, passed as --env-file "
             "to docker run.",
    ),
    detach: bool = typer.Option(
        False, "--detach", "-d",
        help="Run container in the background (container mode only).",
    ),
    name: str | None = typer.Option(
        None, "--container-name",
        help="Container name (container mode only). Defaults to "
             "AGENT_ID from env file.",
    ),
    network: str | None = typer.Option(
        None, "--network",
        help="Docker network to join (container mode only). Defaults "
             "to DOCKER_NETWORK from env file.",
    ),
) -> None:
    """Start the storefront HTTP server."""
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
            "arkhai:storefront",
        ]
        run_step("Start storefront (docker run arkhai:storefront)", cmd, REPO_ROOT)
        return
    container_only = [
        f for f, v in [("--detach", detach), ("--container-name", name), ("--network", network)]
        if v
    ]
    if container_only:
        typer.echo(f"{', '.join(container_only)} ignored (only applies to container mode).")
    cmd = ["make", "-f", "Makefile.agent", "serve-a2a"]
    if env:
        cmd.append(f"ENV_FILE={env}")
    run_step("Start storefront (make serve-a2a)", cmd, REPO_ROOT / "storefront")


# ---------------------------------------------------------------------------
# Group registrations
# ---------------------------------------------------------------------------

app.add_typer(logs_app, name="logs", help="Inspect storefront stage events from the local SQLite log.")
app.add_typer(network_app, name="network", help="Manage ZeroTier network.")
app.add_typer(registry_app, name="registry", help="Manage the registry indexer server.")
app.add_typer(portfolio_app, name="portfolio", help="Manage local resource portfolio data.")
app.add_typer(policy_app, name="policy", help="RL policy lifecycle: train, eval, export.")
register_provide_command(app)


if __name__ == "__main__":
    app()
