import typer

from ..common import REPO_ROOT, run_step

registry_app = typer.Typer(no_args_is_help=True)


@registry_app.command("start")
def registry_start() -> None:
    """Start the Registry Indexer server."""
    run_step(
        "Start Registry Indexer (make serve)",
        ["make", "serve"],
        REPO_ROOT / "erc-8004-registry-py",
    )
