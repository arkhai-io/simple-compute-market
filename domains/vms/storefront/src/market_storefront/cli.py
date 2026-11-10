"""Storefront admin CLI — `market-storefront` console script.

Provider-side commands for managing a running storefront. Buyer
operations live in arkhai-vms-buyer (`market` console script). The two
ship as separate wheels; install both if you both buy and sell.

Subcommands:
    serve        Run the storefront HTTP server in-process.
    publish      Post listings from the agent DB. Mirror of
                 `market buy` on the buyer side.
    escrow       Seller-side escrow lifecycle (claim, refund, show).
    settlement    Inspect readiness and administer installed mechanisms.
    pool-override
                 Set, show, list, or delete the storefront's own terms and
                 listing shapes for one site's pool.
    check-payments
                 Read one account's balance from the payments service with the
                 storefront's own configuration, credential and trust.
    check-mediation
                 Read a dispute authority's respondent listing with the
                 storefront's own dispute credential and trust.
    network      Join the operator's ZeroTier network and list peers.
    config       Inspect or edit the user config.toml.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import httpx
import typer
from market_arkhai_mediation.access_check import check_configured_mediation_access
from market_arkhai_payments import check_configured_payments_access
from market_deal_lifecycle.configuration import DisputeCredential, dispute_config

from .cli_logs import logs_app
from .cli_publish import register as register_publish_command
from .groups.config import config_app
from .groups.escrow import escrow_app
from .groups.network import network_app
from .groups.pool_overrides import pool_override_app
from .groups.settlement import settlement_app

app = typer.Typer(no_args_is_help=True)


def version_callback(value: bool) -> None:
    if value:
        try:
            __version__ = version("arkhai-vms-storefront")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"market-storefront version {__version__}")
        raise typer.Exit()


def _config_path_callback(value: str | None) -> str | None:
    """Override the TOML loader path before any subcommand body runs."""
    if value:
        from market_config.config_loader import set_user_config_path

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
        help="Path to an explicit storefront.toml. Defaults to "
        "$XDG_CONFIG_HOME/arkhai/storefront.toml.",
    ),
) -> None:
    """market-storefront — provider-side admin CLI."""
    pass


# ---------------------------------------------------------------------------
# serve — run the storefront HTTP server in-process
# ---------------------------------------------------------------------------


@app.command("serve")
def serve_cmd(
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        help="Bind interface (default 0.0.0.0).",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        help="Override seller.port from config.toml.",
    ),
) -> None:
    """Run the storefront HTTP server (uvicorn, foreground).

    Listings advertise an optional max_duration_seconds ceiling
    (per-row CSV / [seller.pricing] default); buyers supply the actual
    duration at negotiation init.
    """
    from market_storefront.server import run_serve

    run_serve(host=host, port=port)


# ---------------------------------------------------------------------------
# check-payments — prove the storefront's payments access from its own process
# ---------------------------------------------------------------------------


def payments_section() -> Any:
    """The storefront's ``[Settlement.arkhai_payments]`` section, read from the
    configuration ``serve`` reads, or ``None`` when it configures none.

    A configuration that cannot be read raises ``ValueError``.
    """
    # Imported when the command runs, after the root `--config` option: the
    # storefront's settings resolve when its config module is first imported.
    from market_storefront.utils.config import settlement_config_mapping

    return settlement_config_mapping().get("arkhai_payments")


def payments_transport() -> httpx.BaseTransport | None:
    """The transport the check reaches the payments service through; ``None``
    gives the payments client its own."""
    return None


@app.command("check-payments")
def check_payments_cmd(
    account: str = typer.Option(
        ...,
        "--account",
        help="The payments account whose balance is read, normally the seller's "
        "payee account: the service answers only for the credential's own account.",
    ),
) -> None:
    """Read one account's balance with the storefront's payments configuration.

    Prints one JSON outcome, which never carries the credential, and exits 1
    naming the failing step: configuration, credential, transport, or the
    service's refusal. Starts no server, opens no database, and contacts
    nothing but the payments service.
    """
    try:
        outcome = check_configured_payments_access(
            payments_section, account, transport=payments_transport()
        )
    except ValueError as exc:
        raise typer.BadParameter("not a payments account id", param_hint="--account") from exc
    typer.echo(outcome.json_line())
    if not outcome.ok:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# check-mediation — prove the storefront's dispute authority access from its
# own process
# ---------------------------------------------------------------------------


def dispute_credentials() -> list[DisputeCredential]:
    """The storefront's ``[[DisputeCredential]]`` entries, read from the
    configuration ``serve`` reads, its secret overlay included.

    A configuration that cannot be read raises ``ValueError``.
    """
    # Imported when the command runs, after the root `--config` option: the
    # storefront's settings resolve when its config module is first imported.
    from market_storefront.utils.config import settings

    return list(dispute_config(settings.as_dict(), role="seller").credentials)


def mediation_transport() -> httpx.AsyncBaseTransport | None:
    """The transport the check reaches the authority through; ``None`` gives
    the mediation client its own."""
    return None


@app.command("check-mediation")
def check_mediation_cmd(
    origin: str = typer.Option(
        ...,
        "--origin",
        help="The dispute authority's origin, as the storefront's dispute "
        "credential for it names it.",
    ),
) -> None:
    """Read the authority's respondent listing with the storefront's credential.

    Prints one JSON outcome, which never carries the credential, and exits 1
    naming the failing step: configuration, credential, transport, or the
    authority's refusal. The read changes nothing at the authority, and its
    answer is not judged: any listing is access. Starts no server, opens no
    database, and contacts nothing but the authority.
    """
    try:
        outcome = check_configured_mediation_access(
            dispute_credentials, origin, transport=mediation_transport()
        )
    except ValueError as exc:
        raise typer.BadParameter("not an authority origin", param_hint="--origin") from exc
    typer.echo(outcome.json_line())
    if not outcome.ok:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Group registrations
# ---------------------------------------------------------------------------

app.add_typer(
    logs_app,
    name="logs",
    help="Inspect storefront stage events from the local SQLite log.",
)
app.add_typer(
    network_app,
    name="network",
    help="Join the operator's ZeroTier network and list peers.",
)
app.add_typer(
    config_app,
    name="config",
    help="Inspect or edit user config (path/show/get/set/init-user/migrate).",
)
app.add_typer(
    escrow_app, name="escrow", help="Seller-side escrow lifecycle (claim, refund)."
)
app.add_typer(
    settlement_app,
    name="settlement",
    help="Inspect readiness and administer installed settlement mechanisms.",
)
app.add_typer(
    pool_override_app,
    name="pool-override",
    help="Set, show, list, or delete the storefront's own terms for one site's pool.",
)
register_publish_command(app)


if __name__ == "__main__":
    app()
