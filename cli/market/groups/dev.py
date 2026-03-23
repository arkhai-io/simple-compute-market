import sys

import typer

from ..common import REPO_ROOT, run_step

dev_app = typer.Typer(no_args_is_help=True)


def _local_contracts_command(rpc_url: str) -> list[str]:
    return [
        sys.executable,
        "scripts/deploy_local_contracts.py",
        "--rpc-url",
        rpc_url,
    ]


@dev_app.command("test-env")
def dev_test_env() -> None:
    """As a Developer, run the Anvil test env."""
    run_step(
        "Start Anvil test env (make test-env)",
        ["make", "test-env"],
        REPO_ROOT / "core" / "agent",
    )


@dev_app.command("deploy-contracts")
def dev_deploy_contracts(
    rpc_url: str = typer.Option(
        ...,
        "--rpc-url",
        "-r",
        help="RPC URL for the live local Anvil/EnvTestManager endpoint.",
    ),
) -> None:
    """As a Developer, deploy the local ERC-8004 contracts to the given RPC URL."""
    run_step(
        f"Deploy local ERC-8004 contracts to {rpc_url}",
        _local_contracts_command(rpc_url),
        REPO_ROOT,
    )


@dev_app.command("deploy-registry")
def dev_deploy_registry(
    rpc_url: str = typer.Option(
        ...,
        "--rpc-url",
        "-r",
        help="Deprecated alias for deploy-contracts.",
    ),
) -> None:
    """Deprecated alias for deploy-contracts."""
    dev_deploy_contracts(rpc_url)
