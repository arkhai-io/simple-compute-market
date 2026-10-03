"""Seller-side introduction administration: re-delivery of a revealed introduction."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import typer

contact_app = typer.Typer(
    no_args_is_help=True, help="Introduction-only settlement (contact exchange)."
)


def _contact_exchange() -> tuple[Any, Any]:
    """This storefront's contact exchange and seller delivery, as the server builds them."""
    from market_settlement_runtime import SettlementSQLiteRepository

    from market_storefront.contact_exchange import (
        build_vm_contact_exchange,
        build_vm_introduction_delivery,
    )
    from market_storefront.services.capacity_client import _capacity_settings
    from market_storefront.settlement_composition import (
        build_storefront_settlement_registry,
    )
    from market_storefront.utils.config import (
        resolve_marketplace_signer,
        settlement_config_mapping,
        storefront_domain_registry,
    )
    from market_storefront.utils.sqlite_client import get_sqlite_client

    sites, _placement = _capacity_settings()
    db = get_sqlite_client(registry=storefront_domain_registry())
    delivery = build_vm_introduction_delivery(
        known_origins=tuple(sites), signer=resolve_marketplace_signer()
    )
    settlement = SimpleNamespace(
        settlement_config=build_storefront_settlement_registry().resolve(
            settlement_config_mapping(), role="seller"
        ),
        repository=SettlementSQLiteRepository(db.db_path, apply_migrations=False),
        # Re-delivery reads the durable reveal and drives no obligation.
        runtime=None,
    )
    composition = build_vm_contact_exchange(
        sqlite_client=db,
        settlement_composition=settlement,
        known_origins=tuple(sites),
        delivery=delivery,
    )
    return composition, delivery


@contact_app.command("redeliver")
def redeliver(
    obligation_ref: str = typer.Option(
        ...,
        "--obligation-ref",
        help="The deal whose revealed introduction should be sent again.",
    ),
) -> None:
    """Send an already-revealed introduction to its origin's sinks again."""

    from market_contact_exchange import IntroductionPayloadsDeletedError

    composition, delivery = _contact_exchange()
    if delivery is None:
        raise typer.BadParameter("no delivery sinks are configured")
    try:
        outcomes = delivery.redeliver(
            *asyncio.run(composition.seller_view(obligation_ref))
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
                {"sink": outcome.sink, "delivered": outcome.delivered, "detail": outcome.describe()}
                for outcome in outcomes
            ],
            sort_keys=True,
        )
    )
