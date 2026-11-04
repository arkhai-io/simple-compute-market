"""Receipt-time VM surrender and signed delivery reports through the buyer half."""

from __future__ import annotations

import asyncio
import json
import time

import typer
from market_deal_lifecycle_contracts.models import Accepted
from rich.console import Console

from . import common
from .deal_helpers import (
    accepted_settlement_mechanism, load_deal_context,
    make_deal_publisher_trust_resolver, open_run_log,
)
from .lifecycle import run_sync
from .settlement_composition import buyer_stage, resolve_buyer_settlement_policy
from .settlement_stages import BuyerResumeContext


def run_end_from_log(*, run_id, wait_timeout=0, poll_interval=1, identity=None):
    identity = identity or common.resolve_recovery_buyer_identity(run_id)
    deal = load_deal_context(run_id, signer=identity.signer)
    stage = buyer_stage(accepted_settlement_mechanism(deal))
    log = open_run_log(run_id, signer=identity.signer, profile_id=identity.profile_id)
    context = BuyerResumeContext(
        run_id=run_id, deal=deal, log=log, signer=identity.signer,
        resolve_seller_principals=make_deal_publisher_trust_resolver(run_id, deal, identity.signer),
        resolve_policy=resolve_buyer_settlement_policy, resolve_address_book=common.chain_address_book,
        poll_interval=poll_interval, timeout=60, console=Console(),
    )

    async def end():
        async with stage.lifecycle(context) as lifecycle:
            progress = await lifecycle.end_delivery(deal.negotiation_id)
            log.event("delivery_end", **progress.model_dump(mode="json"))
            delivery = progress.acknowledgement.delivery if progress.acknowledgement else None
            deadline = time.monotonic() + wait_timeout
            while wait_timeout > 0:
                # Direct signed delivery reads are independent of payment or
                # mediation availability; an unreachable authority cannot hide
                # site evidence or block proof of capacity return.
                observed = await lifecycle.peer.read(deal.negotiation_id)
                delivery = observed.delivery
                if delivery.progress == "released" or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            return {
                "progress": progress.model_dump(mode="json"),
                "delivery_view": delivery.model_dump(mode="json") if delivery else None,
                "capacity_released": delivery is not None and delivery.progress == "released",
            }

    result = run_sync(end)
    log.event("delivery_end_observed", **result)
    return result


def register(app):
    @app.command("end")
    def end(
        run_id: str = typer.Option(..., "--from", "--run", "-r"),
        wait_timeout: float = typer.Option(0, "--wait-timeout", min=0),
        poll_interval: float = typer.Option(1, "--poll-interval", min=0.01),
    ):
        """End VM delivery now; report payment, receipt, case and capacity separately.

        There is no historical end-time flag. Once-only and Alkahest surrender
        invent no refund; a queued teardown is never reported as released.
        Retry the same command to recover an unavailable stop or filing.
        """
        try:
            result = run_end_from_log(
                run_id=run_id, wait_timeout=wait_timeout, poll_interval=poll_interval,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        typer.echo(json.dumps(result, sort_keys=True))
        if result["progress"]["delivery"]["status"] != Accepted().status:
            raise typer.Exit(1)
        if wait_timeout > 0 and not result["capacity_released"]:
            raise typer.Exit(1)
