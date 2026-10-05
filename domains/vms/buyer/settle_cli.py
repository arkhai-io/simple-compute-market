"""Resume the immutable accepted VM settlement through its declared buyer stage."""

from __future__ import annotations

import typer
from core_buyer.buyer_config import ResolvedBuyerIdentity
from rich.console import Console

from .buy_orchestrator import (
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
)
from . import common
from .deal_helpers import (
    accepted_settlement_mechanism,
    load_deal_context,
    make_deal_publisher_trust_resolver,
    open_run_log,
)
from .settlement_composition import (
    buyer_stage,
    resolve_alkahest_address_config_path,
    resolve_buyer_settlement_policy,
)
from .settlement_stages import BuyerResumeContext


def run_settle_from_log(
    *, run_id: str, poll_interval: float, settlement_timeout: float,
    console: Console | None = None, identity: ResolvedBuyerIdentity | None = None,
) -> dict:
    """Resolve accepted support before any mechanism resources or seller effects."""
    identity = identity or common.resolve_recovery_buyer_identity(run_id)
    signer = identity.signer
    try:
        deal = load_deal_context(run_id, signer=signer)
        stage = buyer_stage(accepted_settlement_mechanism(deal))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    log = open_run_log(run_id, signer=signer, profile_id=identity.profile_id)
    log.event("settle_resumed")
    return stage.resume(BuyerResumeContext(
        run_id=run_id, deal=deal, log=log, signer=signer,
        resolve_seller_principals=make_deal_publisher_trust_resolver(run_id, deal, signer),
        resolve_policy=resolve_buyer_settlement_policy,
        resolve_address_config=resolve_alkahest_address_config_path,
        poll_interval=poll_interval, timeout=settlement_timeout,
        console=console or Console(),
    ))


def register(app: typer.Typer) -> None:
    """Register the top-level `market settle` command."""

    @app.command("settle")
    def settle(
        run_id: str = typer.Option(
            ...,
            "--from",
            "--run",
            "-r",
            help="Buyer run-id with an accepted settlement to resume (see `market logs runs`).",
        ),
        poll_interval: float = typer.Option(
            DEFAULT_SETTLEMENT_POLL_INTERVAL,
            "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            DEFAULT_SETTLEMENT_TIMEOUT,
            "--settlement-timeout",
            help="Max seconds to wait for provisioning before giving up.",
        ),
    ) -> None:
        """Resume a buy from the post-negotiation point.

        Reads the accepted settlement from the buyer run-log, starts or resumes
        its pinned obligation, submits fulfillment to the seller, and polls until
        terminal. The same run-log is appended throughout.

        Requires the run-log to contain an accepted negotiation outcome.
        For mid-negotiation resume use `market buy --from <id>` instead.
        """
        run_settle_from_log(
            run_id=run_id,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
        )