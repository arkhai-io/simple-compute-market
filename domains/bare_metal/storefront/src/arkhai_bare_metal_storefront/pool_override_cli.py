"""`bare-metal-storefront pool-override`: the storefront's own per-pool terms.

A bare-metal override states settlement clauses, lease-duration bounds, and
asking rates for one pool at one site. It states no shapes: a machine's shape
is its declaration. Region and backing are the site's. The offering mode is
always named, never defaulted.

Every command calls the storefront's administrator API over the pool-override
kit's client and never reads the database, signing and connecting as
``admin_cli`` says. An accepted write refreshes the storefront's held projection
of the site and wakes its publication loop, which publishes under it.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import typer

from .admin_cli import reporting_failures, storefront_admin_client

pool_override_app = typer.Typer(no_args_is_help=True)

_STOREFRONT_URL = typer.Option(
    None,
    "--storefront-url",
    "-a",
    help="Storefront base URL; defaults to the configured base_url.",
)
_SITE = typer.Option(..., "--site", help="The site the pool belongs to.")
_POOL = typer.Option(..., "--pool", help="The pool, as its site names it.")
_MODE = typer.Option(..., "--mode", help="The offering mode, such as bare_metal.")


@contextlib.contextmanager
def _client(explicit_url: str | None) -> Iterator[Any]:
    # Imported here so the CLI's help and its other commands load none of the
    # pool-override client.
    from market_pool_overrides import SyncPoolOverrideClient

    with storefront_admin_client(explicit_url) as core:
        yield SyncPoolOverrideClient(core)


def _emit(value: Any) -> None:
    typer.echo(json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True))


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
    with reporting_failures(), _client(storefront_url_option) as client:
        _emit(client.put_pool_override(record))


@pool_override_app.command("get")
def pool_override_get(
    site: str = _SITE,
    pool: str = _POOL,
    mode: str = _MODE,
    storefront_url_option: str | None = _STOREFRONT_URL,
) -> None:
    """Show one pool's override for one offering mode."""
    with reporting_failures(), _client(storefront_url_option) as client:
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
    with reporting_failures(), _client(storefront_url_option) as client:
        _emit(client.list_pool_overrides(site_id=site, pool_id=pool))


@pool_override_app.command("delete")
def pool_override_delete(
    site: str = _SITE,
    pool: str = _POOL,
    mode: str = _MODE,
    storefront_url_option: str | None = _STOREFRONT_URL,
) -> None:
    """Delete one pool's override for one offering mode. Idempotent."""
    with reporting_failures(), _client(storefront_url_option) as client:
        _emit(client.delete_pool_override(site, pool, mode))


__all__ = ["pool_override_app"]
