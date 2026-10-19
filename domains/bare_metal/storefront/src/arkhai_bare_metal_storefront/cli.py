"""Command-line entry point for the bare-metal storefront."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

import typer

from .admin_cli import reporting_failures
from .pool_override_cli import pool_override_app
from .publication_cli import close_all_open_listings, run_publication_cycle

app = typer.Typer(no_args_is_help=True)
app.add_typer(
    pool_override_app,
    name="pool-override",
    help="Read and replace the storefront's own per-pool terms over its admin API.",
)


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


@dataclass(frozen=True)
class ServeProcess:
    """What ``serve`` runs: given as the command line's context object, it
    replaces the storefront's HTTP process, which runs when none is given."""

    run: Callable[..., None]


@app.command("serve")
def serve_cmd(
    context: typer.Context,
    host: str = typer.Option("0.0.0.0", "--host", help="Bind interface."),
    port: int | None = typer.Option(
        None, "--port", help="Bind port; defaults to the configured port."
    ),
    root_path: str = typer.Option("", "--root-path", help="ASGI root path."),
) -> None:
    """Run the storefront HTTP process."""
    process = context.find_object(ServeProcess)
    if process is None:
        # Importing the server composes the application; only serve needs it.
        from .server import run_serve

        process = ServeProcess(run=run_serve)
    process.run(host=host, port=port, root_path=root_path)


@app.command("publish")
def publish_cmd(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report what one publication cycle would do, and do none of it.",
    ),
    abort_all: bool = typer.Option(
        False,
        "--abort-all",
        help=(
            "Close every open listing as the seller. Reconciliation does not "
            "reopen a listing its seller closed; resume one to re-list it."
        ),
    ),
    storefront_url: str | None = typer.Option(
        None,
        "--storefront-url",
        "-a",
        help="Storefront base URL; defaults to the configured base_url.",
    ),
) -> None:
    """Run, or preview, one cycle of the running storefront's publication loop.

    The cycle runs in the storefront, through its administrator API, as the
    loop's timer runs it; the command opens no database. ``--abort-all``
    instead closes every open listing as its seller.
    """
    if abort_all and dry_run:
        raise typer.BadParameter("--abort-all cannot be combined with --dry-run")
    with reporting_failures():
        if abort_all:
            report: dict[str, object] = {"closed": close_all_open_listings(storefront_url)}
        else:
            report = run_publication_cycle(storefront_url, dry_run=dry_run)
    typer.echo(json.dumps(report, sort_keys=True))


@app.command("redeliver-introduction")
def redeliver_introduction_cmd(
    obligation_ref: str = typer.Option(
        ...,
        "--obligation-ref",
        help="The deal whose revealed introduction should be sent again.",
    ),
) -> None:
    """Send an already-revealed introduction to this operator's sinks again."""

    import asyncio

    from market_contact_exchange import IntroductionPayloadsDeletedError

    from .runtime import build_runtime_from_configuration

    runtime = build_runtime_from_configuration()
    delivery = runtime.introduction_delivery
    if delivery is None:
        raise typer.BadParameter("no delivery sinks are configured")
    try:
        outcomes = delivery.redeliver(
            *asyncio.run(runtime.contact_exchange.seller_view(obligation_ref))
        )
    except IntroductionPayloadsDeletedError as exc:
        # Nothing was sent: the payloads are gone, and no sink was contacted.
        typer.echo(
            json.dumps(
                {
                    "obligation_ref": obligation_ref,
                    "delivered": False,
                    "payloads_deleted_at": exc.payloads_deleted_at,
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            [
                {
                    "sink": outcome.sink,
                    "delivered": outcome.delivered,
                    "detail": outcome.describe(),
                }
                for outcome in outcomes
            ],
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    app()
