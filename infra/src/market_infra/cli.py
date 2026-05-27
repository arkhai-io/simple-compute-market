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
import typing
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
        help="RPC URL to deploy against (sets ANVIL_RPC_URL / RPC_URL).",
    ),
    alkahest: bool = typer.Option(
        True, "--alkahest/--no-alkahest",
        help="Deploy the Alkahest contract suite by replaying "
             "market-contract-deployer/alkahest-transactions.json (default on). "
             "Disable when alkahest is already deployed on the chain.",
    ),
    eas: bool = typer.Option(
        True, "--eas/--no-eas",
        help="Deploy EAS (Ethereum Attestation Service). Today EAS is "
             "bundled with the alkahest replay — `--no-eas --alkahest` is not "
             "yet a separable mode (TODO upstream in alkahest's deploy "
             "fixture). When the chain already has canonical EAS (most L2s "
             "do), pass `--no-alkahest --no-eas` together with explicit "
             "alkahest deployment.",
    ),
    deployer_key: typing.Optional[str] = typer.Option(
        None, "--deployer-key",
        envvar="ANVIL_PRIVATE_KEY",
        help="Private key of the deployer account. Defaults to the well-known "
             "Anvil account #0 key.",
    ),
) -> None:
    """Deploy the contract suites for the marketplace to the given RPC.

    Two suites:
      Alkahest   — Escrow / arbiter / obligation contracts.
      EAS        — Ethereum Attestation Service (currently bundled with
                   alkahest; standalone toggling is TODO upstream).
    """
    if not (alkahest or eas):
        typer.secho(
            "Nothing to deploy: both suites disabled.",
            err=True, fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)

    if alkahest != eas:
        typer.secho(
            "⚠️  --alkahest and --eas must currently match — EAS is bundled "
            "with the alkahest replay. Standalone EAS deploy / standalone "
            "alkahest-against-existing-EAS are upstream-blocked. Treating "
            f"both as enabled={alkahest}.",
            err=True, fg=typer.colors.YELLOW,
        )

    deployer_env: dict[str, str] = {"RPC_URL": rpc_url, "ANVIL_RPC_URL": rpc_url}
    if deployer_key:
        deployer_env["ANVIL_PRIVATE_KEY"] = deployer_key

    if alkahest:
        # Replays alkahest-transactions.json; deploys EAS as a side-effect.
        _run(
            f"Deploy Alkahest + EAS contracts (replay) to {rpc_url}",
            ["python3", "deploy_alkahest.py"],
            REPO_ROOT / "market-contract-deployer",
            deployer_env,
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
