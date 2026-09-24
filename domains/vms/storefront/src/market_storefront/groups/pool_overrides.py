"""`market-storefront pool-override` — the storefront's own per-pool terms.

An override states SLA, prices, settlement clauses, and listing shapes for one
pool at one site, over whatever the pool's site declares. The storefront checks
a written pool against that site's live projection and reports each stated
shape's feasibility. Region, offering mode, and backing are the site's and
cannot be overridden.

Every command calls the storefront's administrator API; none reads its
database.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import typer
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


def _client(storefront_url: str | None):
    return admin_client(resolve_storefront_url(storefront_url, default_port=8001))


def _emit(value: Any) -> None:
    typer.echo(json.dumps(value, indent=2, sort_keys=True))


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
            "JSON document holding the whole override: site_id, pool_id, and any of "
            "sla, min_price, token, max_duration_seconds, settlements, listing_shapes."
        ),
    ),
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """Replace one pool's override with the record in --file.

    A field the record omits is cleared, not kept.
    """
    record = json.loads(file.read_text())
    if not isinstance(record, dict):
        raise typer.BadParameter("the override document must be a JSON object")
    try:
        with _client(storefront_url) as client:
            written = client.admin_put_pool_override(record)
    except StorefrontClientError as exc:
        raise _failed(exc) from exc
    _emit(asdict(written))
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
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """Show one pool's override."""
    try:
        with _client(storefront_url) as client:
            _emit(asdict(client.admin_get_pool_override(site, pool)))
    except StorefrontClientError as exc:
        raise _failed(exc) from exc


@pool_override_app.command("list")
def pool_override_list(
    site: str | None = typer.Option(None, "--site", help="Only this site's overrides."),
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """List overrides, optionally for one site."""
    try:
        with _client(storefront_url) as client:
            _emit(asdict(client.admin_list_pool_overrides(site_id=site)))
    except StorefrontClientError as exc:
        raise _failed(exc) from exc


@pool_override_app.command("delete")
def pool_override_delete(
    site: str = _SITE,
    pool: str = _POOL,
    storefront_url: str | None = _STOREFRONT_URL,
) -> None:
    """Delete one pool's override; the pool's lower tiers apply again."""
    try:
        with _client(storefront_url) as client:
            _emit(asdict(client.admin_delete_pool_override(site, pool)))
    except StorefrontClientError as exc:
        raise _failed(exc) from exc
