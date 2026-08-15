"""Command-line entry point for the bare-metal storefront."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import typer

app = typer.Typer(no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        installed_version = version("arkhai-bare-metal-storefront")
    except PackageNotFoundError:
        installed_version = "unknown (not installed)"
    typer.echo(f"bare-metal-storefront version {installed_version}")
    raise typer.Exit()


@app.callback()
def main(
    version_flag: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Operate the seller-side bare-metal storefront."""


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind interface."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
    root_path: str = typer.Option("", "--root-path", help="ASGI root path."),
) -> None:
    """Run the storefront HTTP process."""
    from .server import run_serve

    run_serve(host=host, port=port, root_path=root_path)


@app.command("publish")
def publish_cmd() -> None:
    """Publish one authenticated round from fresh trusted-site projections."""

    import json

    from .publication_cli import run_publication_once

    typer.echo(json.dumps(run_publication_once(), sort_keys=True))


if __name__ == "__main__":
    app()
