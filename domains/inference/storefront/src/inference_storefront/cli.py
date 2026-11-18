"""Inference storefront admin CLI — the `inference-storefront` console script.

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
from arkhai_api_selling.publish_route import SyncListingClient
from market_config.config_loader import set_user_config_path
from market_identity import Signer, TrustedIdentitySet
from storefront_client import StorefrontClientError, SyncStorefrontClient

from inference_storefront.model_card import PublishFromQuotaRequest

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
    from inference_storefront.utils.config import BASE_URL_OVERRIDE, settings

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
            __version__ = version("arkhai-inference-storefront")
        except PackageNotFoundError:
            __version__ = "unknown (not installed)"
        typer.echo(f"inference-storefront version {__version__}")
        raise typer.Exit()


def _config_path_callback(value: str | None) -> str | None:
    if value:
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
    """inference-storefront — seller-side admin CLI for the inference domain."""


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind interface."),
    port: int | None = typer.Option(None, "--port", help="Override port from config."),
) -> None:
    """Run the storefront HTTP server (uvicorn, foreground)."""
    # Imported only once ``--config`` has run: the storefront's settings
    # resolve when its config module is first imported.
    from inference_storefront.server import run_serve

    run_serve(host=host, port=port)


@app.command("publish")
def publish_cmd(
    resource_id: str = typer.Option(
        ...,
        "--resource-id",
        help="Quota resource in the inference authority's ledger the listing derives from.",
    ),
    model_card: Path = typer.Option(
        ...,
        "--model-card",
        exists=True,
        dir_okay=False,
        help="JSON file holding the model card the listing publishes.",
    ),
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
    paused: bool = typer.Option(False, "--paused"),
    storefront_url: str | None = typer.Option(
        None, "--storefront-url", "-a", help=_STOREFRONT_URL_HELP
    ),
) -> None:
    """Create + publish a model-card listing backed by a quota resource, through the running storefront.

    Pass the Alkahest rate, token, and chain together to publish an escrow
    option. Omit all three to publish the configured settlement clauses.
    The card's resource, site, and offering mode are taken from the quota.
    """
    # Imported only once ``--config`` has run, as in ``serve``.
    import inference_storefront.container as _container
    # Resolves the settings on import, so it waits for ``--config`` too.
    from inference_storefront.utils.config import (
        CHAINS,
        chain_address_books,
        resolve_identity_signer,
    )

    escrow_requested = any(
        value is not None for value in (price_per_token, token, chain)
    )
    if escrow_address is not None and not escrow_requested:
        typer.echo(
            "--escrow-address requires the Alkahest rate, token, and chain.", err=True
        )
        raise typer.Exit(code=2)
    accepted_escrows: list[dict[str, Any]] = []
    if escrow_requested:
        if price_per_token is None or token is None or chain is None:
            typer.echo(
                "Alkahest publication requires --price-per-token, --token, and --chain together.",
                err=True,
            )
            raise typer.Exit(code=2)
        if not price_per_token.strip().isdigit():
            typer.echo("--price-per-token must be a base-unit integer", err=True)
            raise typer.Exit(code=2)

        address_config_path = None
        if not escrow_address:
            if chain not in CHAINS:
                typer.echo(f"chain {chain!r} is not configured", err=True)
                raise typer.Exit(code=2)
            try:
                address_config_path = chain_address_books()[chain]
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=2) from exc
        accepted_escrows = [
            _container.ALKAHEST_STAGE.accepted_escrow(
                chain_name=chain,
                address_config_path=address_config_path,
                token=token,
                price_per_token=price_per_token,
                escrow_address=escrow_address,
            )
        ]

    signer = resolve_identity_signer()
    url = _storefront_url(storefront_url)
    request = {
        "resource_id": resource_id,
        "accepted_escrows": accepted_escrows,
        "model_card": json.loads(model_card.read_text(encoding="utf-8")),
        "paused": paused,
    }
    try:
        with _open_storefront(url, signer) as client:
            result = SyncListingClient(
                client, seller=signer.identity, request_model=PublishFromQuotaRequest
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
    from inference_storefront.utils.config import resolve_identity_config

    seller = resolve_identity_config().principal
    url = _storefront_url(storefront_url)
    try:
        # The listing route is public, so the read needs no credential.
        with _open_storefront(url, None) as client:
            page = SyncListingClient(
                client, seller=seller, request_model=PublishFromQuotaRequest
            ).list_listings(status=status, limit=limit)
    except (StorefrontClientError, httpx.HTTPError) as exc:
        raise _refused(url, exc) from exc
    typer.echo(json.dumps(dataclasses.asdict(page), indent=2, default=str))


if __name__ == "__main__":
    app()
