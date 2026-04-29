"""`market-infra` — market-operator tools.

The chain, the registry indexer, and the ZeroTier network are run once
per market by the trust authority — not per-agent. They were
previously split across `market dev` (buyer-side dev tooling) and
`market-storefront registry`/`network` (seller-side admin), which
mixed runtime concerns with operator concerns. This CLI consolidates
them under their actual ownership.

Subcommands:
  chain     up / deploy-contracts
  registry  start
  network   install / create / add
"""

from __future__ import annotations

import os
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import typer


# parents[3]: market_infra → src → infra → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


def _run(label: str, cmd: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=str(cwd), check=True, env=env)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


app = typer.Typer(no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        try:
            v = version("market-infra")
        except PackageNotFoundError:
            v = "unknown (not installed)"
        typer.echo(f"market-infra version {v}")
        raise typer.Exit()


@app.callback()
def main(
    version_flag: bool = typer.Option(
        None, "--version", "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """market-infra — operator-side CLI: chain, registry, network admin."""
    pass


# ---------------------------------------------------------------------------
# chain — local Anvil + ERC-8004 contracts
# ---------------------------------------------------------------------------


chain_app = typer.Typer(no_args_is_help=True)


@chain_app.command("up")
def chain_up() -> None:
    """Bring up the local Anvil test chain in a docker container.

    Replaces the buyer's broken `market dev test-env` (which pointed
    at a `core/` directory that no longer exists). Wraps
    `test-env/make deploy` — pulls/builds the arkhai:test-env image
    and runs anvil on the `market` docker network at :8545.
    """
    _run(
        "Start Anvil test env (make deploy)",
        ["make", "deploy"],
        REPO_ROOT / "test-env",
    )


@chain_app.command("deploy-contracts")
def chain_deploy_contracts(
    rpc_url: str = typer.Option(
        ..., "--rpc-url", "-r",
        help="RPC URL to deploy against (sets ANVIL_RPC_URL).",
    ),
) -> None:
    """Deploy the ERC-8004 contracts to the given RPC.

    Replaces the buyer's `market dev deploy-registry`. Wraps
    `npm run deploy:anvil` in `erc-8004-contracts/`.
    """
    _run(
        f"Deploy ERC-8004 contracts to {rpc_url}",
        ["npm", "run", "deploy:anvil"],
        REPO_ROOT / "erc-8004-contracts",
        {"ANVIL_RPC_URL": rpc_url},
    )


# ---------------------------------------------------------------------------
# registry — off-chain registry indexer service
# ---------------------------------------------------------------------------


registry_app = typer.Typer(no_args_is_help=True)


@registry_app.command("start")
def registry_start() -> None:
    """Start the registry indexer server (`registry-service/make serve`).

    Replaces `market-storefront registry start`. The indexer is one
    process per market, not per-seller; it's an operator concern.
    """
    _run(
        "Start Registry Indexer (make serve)",
        ["make", "serve"],
        REPO_ROOT / "registry-service",
    )


# ---------------------------------------------------------------------------
# network — ZeroTier network owner actions
# ---------------------------------------------------------------------------


network_app = typer.Typer(no_args_is_help=True)


@network_app.command("install")
def network_install() -> None:
    """Install the ZeroTier client locally."""
    _run(
        "ZeroTier install (make install)",
        ["make", "install"],
        REPO_ROOT / "infra",
    )


@network_app.command("create")
def network_create() -> None:
    """Create a new ZeroTier network owned by the operator."""
    _run(
        "Create ZeroTier network (make create-network)",
        ["make", "create-network"],
        REPO_ROOT / "infra",
    )


@network_app.command("add")
def network_add(
    member_id: str = typer.Argument(..., help="ZeroTier member node ID to authorize."),
) -> None:
    """Authorize a member node onto the network."""
    _run(
        f"Authorize ZeroTier member {member_id}",
        ["make", "add-node", f"NODE_ID={member_id}"],
        REPO_ROOT / "infra",
    )


# ---------------------------------------------------------------------------
# Group registrations
# ---------------------------------------------------------------------------


app.add_typer(chain_app, name="chain", help="Local chain admin (Anvil up, deploy contracts).")
app.add_typer(registry_app, name="registry", help="Run the off-chain registry indexer service.")
app.add_typer(network_app, name="network", help="ZeroTier network-owner actions (install, create, add).")


if __name__ == "__main__":
    app()
