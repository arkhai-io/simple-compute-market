"""The domain's command group: listing, buy, negotiate, settle, and settlement readiness."""

from __future__ import annotations

import asyncio
import json

import typer

from arkhai_api_buying import buy, negotiate, settle
from arkhai_api_buying.listing import listing_app
from arkhai_api_buying.settlement_composition import BuyerSettlementComposition


def _settlement_app(settlement: BuyerSettlementComposition) -> typer.Typer:
    def status(
        as_json: bool = typer.Option(False, "--json", help="Emit sanitized JSON."),
    ) -> None:
        config, statuses = asyncio.run(settlement.readiness())
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": config.schema_version,
                        "priority": list(config.priority),
                        "mechanisms": [status.safe_projection() for status in statuses],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        else:
            for status in statuses:
                state = (
                    "ready"
                    if status.ready
                    else "disabled"
                    if not status.enabled
                    else "unready"
                )
                typer.echo(f"{status.mechanism}: {state}")
                for blocker in status.blockers:
                    typer.echo(f"  {blocker.code}: {blocker.message}")
        if not any(status.ready for status in statuses):
            raise typer.Exit(1)

    app = typer.Typer(
        no_args_is_help=True,
        help="Shared settlement profile and readiness commands.",
    )
    app.command("status")(status)
    for registration in settlement.registry().registrations:
        if registration.command_group is not None:
            app.add_typer(registration.command_group, name=registration.config_key)
    return app


def command_group(settlement: BuyerSettlementComposition) -> typer.Typer:
    """The group a buyer plugin registers under its bundle's ``command`` name."""
    group = typer.Typer(no_args_is_help=True)
    group.add_typer(
        listing_app(settlement),
        name="listing",
        help=f"Browse {settlement.contributions.noun} listings (list/show).",
    )
    buy.register(group, settlement=settlement)
    negotiate.register(group, settlement=settlement)
    settle.register(group, settlement=settlement)
    group.add_typer(_settlement_app(settlement), name="settlement")
    return group
