"""Seller notice commands through the signed lifecycle API."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import typer
from market_deal_lifecycle_client import SyncSellerLifecycleClient

from .admin_cli import reporting_failures, storefront_admin_client

deals_app = typer.Typer(no_args_is_help=True)


@contextlib.contextmanager
def lifecycle_client(storefront_url: str | None) -> Iterator[SyncSellerLifecycleClient]:
    with storefront_admin_client(storefront_url) as core:
        yield SyncSellerLifecycleClient(core)


@deals_app.command("preempt")
def preempt(
    negotiation_id: str,
    operation_key: str = typer.Option(..., "--operation-key", help="Keep this key and --at unchanged on retry."),
    at: int | None = typer.Option(None, "--at", min=0, help="Requested Unix second; the authority enforces notice."),
    storefront_url: str | None = typer.Option(None, "--storefront-url", "-a"),
) -> None:
    """Submit seller notice; only the authority's returned records establish an end."""
    with reporting_failures(), lifecycle_client(storefront_url) as client:
        result = client.notice(negotiation_id, operation_key=operation_key, at=at)
    typer.echo(result.model_dump_json(indent=2))
    if result.outcome.status == "rejected":
        raise typer.Exit(1)
