"""`bare-metal-storefront pool-override`: the storefront's own per-pool terms.

A bare-metal override states settlement clauses, lease-duration bounds, and
asking rates for one pool at one site. It states no shapes: a machine's shape
is its declaration. Region and backing are the site's. The offering mode is
always named, never defaulted.

Every command calls the storefront's administrator API over the pool-override
kit's client and never reads the database. It signs as the storefront's own
marketplace signer, from the identity inputs the server reads, so that identity
must be listed in ``BARE_METAL_STOREFRONT_ADMIN_IDENTITIES``. A write takes
effect at the storefront's next publication run.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import typer

pool_override_app = typer.Typer(no_args_is_help=True)

_DEFAULT_STOREFRONT_URL = "http://localhost:8000"

_STOREFRONT_URL = typer.Option(
    None,
    "--storefront-url",
    help=(
        "Storefront base URL; defaults to BARE_METAL_STOREFRONT_PUBLIC_URL, "
        f"then {_DEFAULT_STOREFRONT_URL}."
    ),
)
_SITE = typer.Option(..., "--site", help="The site the pool belongs to.")
_POOL = typer.Option(..., "--pool", help="The pool, as its site names it.")
_MODE = typer.Option(..., "--mode", help="The offering mode, such as bare_metal.")


def storefront_url(explicit: str | None, environ: Mapping[str, str]) -> str:
    """The flag, else the storefront's public URL, else the local default."""
    url = explicit or environ.get("BARE_METAL_STOREFRONT_PUBLIC_URL") or ""
    return url.rstrip("/") or _DEFAULT_STOREFRONT_URL


@contextlib.contextmanager
def _client(explicit_url: str | None) -> Iterator[Any]:
    # Imported here so the CLI's help and its other commands load none of the
    # client or identity stack.
    from market_identity import TrustedIdentitySet
    from market_pool_overrides import SyncPoolOverrideClient
    from storefront_client import SyncStorefrontClient

    from .runtime import storefront_signer_from_environment

    try:
        signer = storefront_signer_from_environment(os.environ)
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(
            "the storefront identity (BARE_METAL_STOREFRONT_IDENTITY_SCHEME, "
            "BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER) and a matching "
            "ARKHAI_IDENTITY_CREDENTIAL are required"
        ) from exc
    with SyncStorefrontClient(
        storefront_url(explicit_url, os.environ),
        signer=signer,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    ) as core:
        yield SyncPoolOverrideClient(core)


def _emit(value: Any) -> None:
    typer.echo(json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True))


@contextlib.contextmanager
def _reporting_failures() -> Iterator[None]:
    from storefront_client import StorefrontClientError

    try:
        yield
    except StorefrontClientError as exc:
        typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc


@pool_override_app.command("set")
def pool_override_set(
    file: Path = typer.Option(
        ...,
        "--file",
        "-f",
        exists=True,
        dir_okay=False,
        help=(
            "JSON document holding the whole override: site_id, pool_id, "
            "offering_mode, and any of settlements, asking_rates, and terms "
            "(min_duration_seconds, max_duration_seconds)."
        ),
    ),
    storefront_url_option: str | None = _STOREFRONT_URL,
) -> None:
    """Replace one pool's override for one offering mode with the record in --file."""
    try:
        record = json.loads(file.read_text())
    except ValueError as exc:
        raise typer.BadParameter(f"{file} is not JSON: {exc}") from exc
    with _reporting_failures(), _client(storefront_url_option) as client:
        _emit(client.put_pool_override(record))


@pool_override_app.command("get")
def pool_override_get(
    site: str = _SITE,
    pool: str = _POOL,
    mode: str = _MODE,
    storefront_url_option: str | None = _STOREFRONT_URL,
) -> None:
    """Show one pool's override for one offering mode."""
    with _reporting_failures(), _client(storefront_url_option) as client:
        _emit(client.get_pool_override(site, pool, mode))


@pool_override_app.command("list")
def pool_override_list(
    site: str | None = typer.Option(None, "--site", help="Narrow to one site."),
    pool: str | None = typer.Option(None, "--pool", help="Narrow to one site's pool."),
    storefront_url_option: str | None = _STOREFRONT_URL,
) -> None:
    """List overrides, optionally narrowed to a site or one site's pool."""
    if pool is not None and site is None:
        raise typer.BadParameter("--pool requires --site")
    with _reporting_failures(), _client(storefront_url_option) as client:
        _emit(client.list_pool_overrides(site_id=site, pool_id=pool))


@pool_override_app.command("delete")
def pool_override_delete(
    site: str = _SITE,
    pool: str = _POOL,
    mode: str = _MODE,
    storefront_url_option: str | None = _STOREFRONT_URL,
) -> None:
    """Delete one pool's override for one offering mode. Idempotent."""
    with _reporting_failures(), _client(storefront_url_option) as client:
        _emit(client.delete_pool_override(site, pool, mode))


__all__ = ["pool_override_app", "storefront_url"]
