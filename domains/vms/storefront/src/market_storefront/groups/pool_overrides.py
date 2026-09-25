"""`market-storefront pool-override` — the storefront's own per-pool terms.

An override states listing shapes, settlement clauses, and its market's terms
for one pool at one site, in one offering mode, over whatever the pool's site
declares. The storefront checks a written pool against that site's live
projection and reports each stated shape's feasibility. Region and backing are
the site's and cannot be overridden, and the offering mode is always named.

Every command calls the storefront's administrator API; none reads its
database.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import typer
from market_pool_overrides import SyncPoolOverrideClient
from storefront_client import StorefrontClientError

from ..cli_common import admin_client, resolve_storefront_url

pool_override_app = typer.Typer(no_args_is_help=True)

_STOREFRONT_URL = typer.Option(
    None,
    "--storefront-url",
    "-a",
    help="Storefront base URL (default: base_url from storefront.toml).",
)
_SITE = typer.Option(..., "--site", help="The site the pool belongs to.")
_POOL = typer.Option(..., "--pool", help="The pool, as its site names it.")
_MODE = typer.Option(..., "--mode", help="The offering mode the override is for, such as vm.")


@contextlib.contextmanager
def _client(storefront_url: str | None) -> Iterator[SyncPoolOverrideClient]:
    """The override client over an administrator session this command owns."""
    with admin_client(resolve_storefront_url(storefront_url, default_port=8001)) as core:
        yield SyncPoolOverrideClient(core)


def _emit(value: Any) -> None:
    typer.echo(json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True))


def _failed(exc: StorefrontClientError) -> typer.Exit:
    typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
    return typer.Exit(code=1)


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
            "offering_mode, and any of listing_shapes, settlements, and terms."
        ),
    ),
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """Replace one pool's override for one offering mode with the record in --file.

    A field the record omits is cleared, not kept.
    """
    record = json.loads(file.read_text())
    if not isinstance(record, dict):
        raise typer.BadParameter("the override document must be a JSON object")
    try:
        with _client(storefront_url) as client:
            written = client.put_pool_override(record)
    except StorefrontClientError as exc:
        raise _failed(exc) from exc
    _emit(written)
    infeasible = [entry for entry in written.feasibility if not entry.feasible]
    if infeasible:
        typer.secho(
            f"{len(infeasible)} shape(s) no member of the site's projection is "
            "feasible for; they publish nothing.",
            err=True,
            fg=typer.colors.YELLOW,
        )


@pool_override_app.command("get")
def pool_override_get(
    site: str = _SITE,
    pool: str = _POOL,
    mode: str = _MODE,
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """Show one pool's override for one offering mode."""
    try:
        with _client(storefront_url) as client:
            _emit(client.get_pool_override(site, pool, mode))
    except StorefrontClientError as exc:
        raise _failed(exc) from exc


@pool_override_app.command("list")
def pool_override_list(
    site: str | None = typer.Option(None, "--site", help="Only this site's overrides."),
    pool: str | None = typer.Option(
        None, "--pool", help="Only this pool's overrides; requires --site."
    ),
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """List overrides, optionally for one site or one site's pool."""
    if pool is not None and site is None:
        raise typer.BadParameter("--pool requires --site")
    try:
        with _client(storefront_url) as client:
            _emit(client.list_pool_overrides(site_id=site, pool_id=pool))
    except StorefrontClientError as exc:
        raise _failed(exc) from exc


@pool_override_app.command("delete")
def pool_override_delete(
    site: str = _SITE,
    pool: str = _POOL,
    mode: str = _MODE,
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """Delete one pool's override for one offering mode; its lower tiers apply again."""
    try:
        with _client(storefront_url) as client:
            _emit(client.delete_pool_override(site, pool, mode))
    except StorefrontClientError as exc:
        raise _failed(exc) from exc
