"""API-tokens storefront admin CLI — `apitokens-storefront` console script.

Subcommands:
    serve      Run the storefront HTTP server in-process.
    publish    Create + publish a listing backed by a quota resource.
    listings   List the storefront's local listings.
"""

from __future__ import annotations

import asyncio
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True)


def version_callback(value: bool) -> None:
    if value:
        try:
            __version__ = version("arkhai-apitokens-storefront")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"apitokens-storefront version {__version__}")
        raise typer.Exit()


def _config_path_callback(value: str | None) -> str | None:
    if value:
        from market_config.config_loader import set_user_config_path

        set_user_config_path(Path(value))
    return value


@app.callback()
def main(
    version_flag: bool = typer.Option(
        None, "--version", "-v",
        callback=version_callback, is_eager=True,
        help="Show version and exit.",
    ),
    config_file: str | None = typer.Option(
        None, "--config",
        callback=_config_path_callback, is_eager=True,
        help="Path to an explicit storefront.toml.",
    ),
) -> None:
    """apitokens-storefront — seller-side admin CLI for the API-tokens domain."""


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind interface."),
    port: int | None = typer.Option(None, "--port", help="Override port from config."),
) -> None:
    """Run the storefront HTTP server (uvicorn, foreground)."""
    from apitokens_storefront.server import run_serve

    run_serve(host=host, port=port)


@app.command("publish")
def publish_cmd(
    resource_id: str = typer.Option(
        ..., "--resource-id",
        help="Quota resource in the tokens service's ledger the listing derives from.",
    ),
    service_name: str = typer.Option(..., "--service-name"),
    price_per_token: str = typer.Option(
        ..., "--price-per-token",
        help="Per-token rate in base units of the payment token.",
    ),
    token: str = typer.Option(
        ..., "--token", help="Payment token contract address (0x…).",
    ),
    chain: str = typer.Option(
        ..., "--chain", help="Chain name from [chains.<name>] config.",
    ),
    escrow_address: str | None = typer.Option(
        None, "--escrow-address",
        help="Escrow contract address; resolved from the chain's alkahest "
             "config (erc20 non-unconditional) when omitted.",
    ),
    description: str | None = typer.Option(None, "--description"),
    openapi_url: str | None = typer.Option(None, "--openapi-url"),
    base_url: str | None = typer.Option(
        None, "--base-url", help="Base URL of the token-gated service.",
    ),
    paused: bool = typer.Option(False, "--paused"),
) -> None:
    """Create + publish a listing backed by a quota resource.

    The accepted escrow advertises a unit rate
    ``{field: "amount", per: "token", value: <price-per-token>}`` — the
    buyer's quantity scales it to the absolute amount at negotiation.
    """
    from apitokens_storefront.services.listing_service import ListingService
    from apitokens_storefront.utils.config import CHAINS
    from apitokens_storefront.utils.sqlite_client import get_sqlite_client

    if not price_per_token.strip().isdigit():
        typer.echo("--price-per-token must be a base-unit integer", err=True)
        raise typer.Exit(code=2)

    resolved_escrow = escrow_address
    if not resolved_escrow:
        chain_cfg = CHAINS.get(chain)
        if chain_cfg is None:
            typer.echo(f"chain {chain!r} is not configured", err=True)
            raise typer.Exit(code=2)
        from market_alkahest.alkahest import (
            get_erc20_escrow_obligation_default,
        )

        resolved_escrow = get_erc20_escrow_obligation_default(
            chain, config_path=chain_cfg.alkahest_address_config_path,
        )

    accepted_escrows = [{
        "chain_name": chain,
        "escrow_address": resolved_escrow.lower(),
        "literal_fields": {"token": token},
        "rates": [{"field": "amount", "per": "token", "value": price_per_token}],
    }]

    svc = ListingService(sqlite_client=get_sqlite_client())
    result = asyncio.run(svc.publish_from_quota(
        resource_id=resource_id,
        service_name=service_name,
        accepted_escrows=accepted_escrows,
        description=description,
        openapi_url=openapi_url,
        base_url=base_url,
        paused=paused,
    ))
    typer.echo(json.dumps(result, indent=2))


@app.command("listings")
def listings_cmd(
    status: str | None = typer.Option(None, "--status"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    """List the storefront's local listings."""
    from apitokens_storefront.utils.sqlite_client import get_sqlite_client

    rows = asyncio.run(
        get_sqlite_client().list_listings(status=status, limit=limit),
    )
    typer.echo(json.dumps(rows, indent=2, default=str))


if __name__ == "__main__":
    app()
