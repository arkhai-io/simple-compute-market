"""`market <command> settle` — resume a selected mechanism from a deal log.

The accepted Agreement names the stage that resumes it: each stage completes
its own settlement step, then polls the seller until credits are issued, and
every stage delivers credentials through the same signed status channel.
"""

from __future__ import annotations

from typing import Any, Optional

import typer
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.orchestration import (
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
)
from rich.console import Console

from arkhai_api_buying import common
from arkhai_api_buying.deal import load_deal_context
from arkhai_api_buying.settlement_composition import BuyerSettlementComposition
from arkhai_api_buying.stages import SettlementResume, StageOptions


def run_settle_from_log(
    settlement: BuyerSettlementComposition,
    *,
    run_id: str,
    identity: ResolvedBuyerIdentity,
    options: StageOptions,
    poll_interval: float,
    settlement_timeout: float,
    console: Optional[Console] = None,
) -> dict:
    """Resume settlement from a buyer run-log.

    Reusable by the group's `settle` and `buy --from`. The accepted
    mechanism's stage completes its settlement step, submits to the seller,
    polls until terminal, and keeps any issued credential in the
    composition's private store.

    Returns the final settle-status body. Raises ``typer.Exit`` on fatal
    errors.
    """
    signer = identity.signer
    deal = load_deal_context(
        settlement,
        run_id,
        signer=signer,
        refresh_publisher_principals=common.make_run_publisher_principals_refresh(
            run_id, signer=signer
        ),
    )
    return settlement.stage(deal.agreement).resume(SettlementResume(
        contributions=settlement.contributions,
        run_id=run_id,
        deal=deal,
        identity=identity,
        settlement_config=lambda: settlement.resolve_policy(identity=identity).config,
        options=options,
        poll_interval=poll_interval,
        settlement_timeout=settlement_timeout,
        console=console or Console(),
        credential_store=settlement.credential_store,
    ))


def register(
    group: typer.Typer,
    *,
    settlement: BuyerSettlementComposition,
) -> None:
    """Register the group's `settle` command."""
    command = settlement.contributions.command_path

    def settle(
        run_id: str = typer.Option(
            ...,
            "--from",
            "--run",
            "-r",
            help=f"Buyer run-id from a prior `{command} negotiate` to resume from (see the buy-runs log directory).",
        ),
        poll_interval: float = typer.Option(
            DEFAULT_SETTLEMENT_POLL_INTERVAL,
            "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            DEFAULT_SETTLEMENT_TIMEOUT,
            "--settlement-timeout",
            help="Max seconds to wait for issuance before giving up.",
        ),
        **stage_values: Any,
    ) -> None:
        """Resume a credit buy from the post-negotiation point.

        Reads the buyer run-log for `<run_id>`, completes the accepted
        mechanism's settlement step if it is not already done, asks the
        seller to settle, and polls until terminal. The issued key is shown
        once and kept in the buyer's private credential store; the run-log
        records only its non-secret fields (``credentials_delivered``).

        Requires the run-log to contain an `agreed` negotiation outcome.
        """
        options, _rest = settlement.split_options(stage_values, "settle")
        run_settle_from_log(
            settlement,
            run_id=run_id,
            identity=common.resolve_recovery_buyer_identity(run_id),
            options=options,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
        )

    group.command("settle")(settlement.add_options(settle, "settle"))
