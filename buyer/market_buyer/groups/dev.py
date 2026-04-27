import typer

from ..common import REPO_ROOT, run_step

dev_app = typer.Typer(no_args_is_help=True)


@dev_app.command("test-env")
def dev_test_env() -> None:
    """As a Developer, run the Anvil test env."""
    run_step(
        "Start Anvil test env (make test-env)",
        ["make", "test-env"],
        REPO_ROOT / "core" / "agent",
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
    """As a Developer, deploy the ERC-8004 contracts to the given RPC_URL."""
    run_step(
        f"Deploy ERC-8004 contracts to {rpc_url}",
        ["npm", "run", "deploy:anvil"],
        REPO_ROOT / "erc-8004-contracts",
        {"ANVIL_RPC_URL": rpc_url},
    )
