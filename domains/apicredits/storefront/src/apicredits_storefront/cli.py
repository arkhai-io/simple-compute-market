"""API-credits storefront admin CLI — `apicredits-storefront` console script.

Subcommands:
    serve      Run the storefront HTTP server in-process.
    publish    Create + publish a listing backed by a quota resource, through
               the running storefront.
    listings   List the running storefront's local listings.

``publish`` and ``listings`` are clients of a running storefront: a listing
created with no storefront serving it is one no buyer can negotiate, so neither
command builds the storefront's services or opens its database.
"""

from __future__ import annotations

import dataclasses
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import httpx
import typer
from market_alkahest.alkahest import get_erc20_escrow_obligation_default
from market_identity import Signer, TrustedIdentitySet
from storefront_client import StorefrontClientError, SyncStorefrontClient

from apicredits_storefront.listing_publication import SyncApiCreditListingClient

app = typer.Typer(no_args_is_help=True)

_STOREFRONT_URL_HELP = (
    "The running storefront's origin; the configured base_url, else "
    "http://localhost:<port>, when omitted."
)


def _open_storefront(url: str, signer: Signer | None) -> SyncStorefrontClient:
    """The typed client the listing commands reach the storefront through,
    signing as the storefront's own principal when ``signer`` is given."""
    if signer is None:
        return SyncStorefrontClient(url)
    return SyncStorefrontClient(
        url,
        signer=signer,
        caller_role="seller",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    )


def _storefront_url(explicit: str | None) -> str:
    # Imported when a command runs, after the root `--config` option: the
    # storefront's settings resolve when its config module is first imported.
    from apicredits_storefront.utils.config import BASE_URL_OVERRIDE, settings

    return explicit or BASE_URL_OVERRIDE or f"http://localhost:{settings.port}"


def _refused(url: str, exc: Exception) -> typer.Exit:
    """Report a refusal or an unreachable storefront, naming where it was sent."""
    if isinstance(exc, httpx.HTTPError):
        typer.echo(
            f"no storefront answered at {url} ({type(exc).__name__})", err=True
        )
    else:
        typer.echo(f"the storefront at {url} refused: {exc}", err=True)
    return typer.Exit(code=1)


def version_callback(value: bool) -> None:
    if value:
        try:
            __version__ = version("arkhai-apicredits-storefront")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"apicredits-storefront version {__version__}")
        raise typer.Exit()


def _config_path_callback(value: str | None) -> str | None:
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
        help="Path to an explicit storefront.toml.",
    ),
) -> None:
    """apicredits-storefront — seller-side admin CLI for the API-credits domain."""


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind interface."),
    port: int | None = typer.Option(None, "--port", help="Override port from config."),
) -> None:
    """Run the storefront HTTP server (uvicorn, foreground)."""
    from apicredits_storefront.server import run_serve

    run_serve(host=host, port=port)


@app.command("publish")
def publish_cmd(
    resource_id: str = typer.Option(
        ...,
        "--resource-id",
        help="Quota resource in the credits service's ledger the listing derives from.",
    ),
    service_name: str = typer.Option(..., "--service-name"),
    price_per_token: str | None = typer.Option(
        None,
        "--price-per-token",
        help=(
            "Optional Alkahest rate in base units per token; omit to publish "
            "configured settlement clauses only."
        ),
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Alkahest payment token contract address (0x…).",
    ),
    chain: str | None = typer.Option(
        None,
        "--chain",
        help="Alkahest chain name from [chains.<name>] config.",
    ),
    escrow_address: str | None = typer.Option(
        None,
        "--escrow-address",
        help="Alkahest escrow contract; resolved from the chain config when omitted.",
    ),
    description: str | None = typer.Option(None, "--description"),
    openapi_url: str | None = typer.Option(None, "--openapi-url"),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Base URL of the token-gated service.",
    ),
    paused: bool = typer.Option(False, "--paused"),
    storefront_url: str | None = typer.Option(
        None, "--storefront-url", "-a", help=_STOREFRONT_URL_HELP
    ),
) -> None:
    """Create + publish a listing backed by a quota resource.

    Pass the Alkahest rate, token, and chain together to publish an escrow
    option. Omit all three to publish configured settlement clauses, such as
    Arkhai payments, without requiring an EVM chain. The running storefront
    creates the listing; the command signs as the storefront's own principal,
    from the configuration and ``ARKHAI_IDENTITY_CREDENTIAL``.
    """
    # Imported only once ``--config`` has run: the storefront's settings
    # resolve when its config module is first imported.
    from apicredits_storefront.utils.config import CHAINS, resolve_identity_signer

    legacy_requested = any(
        value is not None for value in (price_per_token, token, chain)
    )
    if escrow_address is not None and not legacy_requested:
        typer.echo(
            "--escrow-address requires the Alkahest rate, token, and chain.", err=True
        )
        raise typer.Exit(code=2)
    accepted_escrows: list[dict[str, Any]] = []
    if legacy_requested:
        if price_per_token is None or token is None or chain is None:
            typer.echo(
                "Alkahest publication requires --price-per-token, --token, and --chain together.",
                err=True,
            )
            raise typer.Exit(code=2)
        if not price_per_token.strip().isdigit():
            typer.echo("--price-per-token must be a base-unit integer", err=True)
            raise typer.Exit(code=2)

        resolved_escrow = escrow_address
        if not resolved_escrow:
            chain_cfg = CHAINS.get(chain)
            if chain_cfg is None:
                typer.echo(f"chain {chain!r} is not configured", err=True)
                raise typer.Exit(code=2)
            resolved_escrow = get_erc20_escrow_obligation_default(
                chain, config_path=chain_cfg.alkahest_address_config_path
            )
        accepted_escrows = [
            {
                "chain_name": chain,
                "escrow_address": resolved_escrow.lower(),
                "literal_fields": {"token": token},
                "rates": [
                    {"field": "amount", "per": "token", "value": price_per_token}
                ],
            }
        ]

    signer = resolve_identity_signer()
    url = _storefront_url(storefront_url)
    request = {
        "resource_id": resource_id,
        "service_name": service_name,
        "accepted_escrows": accepted_escrows,
        "description": description,
        "openapi_url": openapi_url,
        "base_url": base_url,
        "paused": paused,
    }
    try:
        with _open_storefront(url, signer) as client:
            result = SyncApiCreditListingClient(
                client, seller=signer.identity
            ).publish_from_quota(request)
    except (StorefrontClientError, httpx.HTTPError) as exc:
        raise _refused(url, exc) from exc
    typer.echo(json.dumps(result.model_dump(mode="json"), indent=2))


@app.command("listings")
def listings_cmd(
    status: str | None = typer.Option(None, "--status"),
    limit: int = typer.Option(50, "--limit"),
    storefront_url: str | None = typer.Option(
        None, "--storefront-url", "-a", help=_STOREFRONT_URL_HELP
    ),
) -> None:
    """List the running storefront's local listings."""
    # Imported only once ``--config`` has run, as in ``publish``.
    from apicredits_storefront.utils.config import resolve_identity_config

    seller = resolve_identity_config().principal
    url = _storefront_url(storefront_url)
    try:
        # The listing route is public, so the read needs no credential: the
        # seller's public principal is all the listing client needs.
        with _open_storefront(url, None) as client:
            page = SyncApiCreditListingClient(client, seller=seller).list_listings(
                status=status, limit=limit
            )
    except (StorefrontClientError, httpx.HTTPError) as exc:
        raise _refused(url, exc) from exc
    typer.echo(json.dumps(dataclasses.asdict(page), indent=2, default=str))


if __name__ == "__main__":
    app()
