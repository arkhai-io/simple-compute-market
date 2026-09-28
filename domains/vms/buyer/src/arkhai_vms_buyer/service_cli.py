"""`market service` — the buyer-side deal servicing engine.

The buyer half of lifecycle work item I.3: after `settle` hands over a
running VM, someone on the buyer's side must keep the deal serviced —
emit signed heartbeats while the service is healthy (the seller's
evidence for heartbeat-gated collection), stop when it is not, and
reclaim the escrow if it expires uncollected. `market service --from
<run_id>` is that engine: a foreground loop over the same run-log the
buy/settle stages share, restartable at any point.

Heartbeats use the same scheme-neutral, body-bound marketplace v2 request
contract as every other buyer action. The authenticated timestamp also
provides the heartbeat's claimed send time, which the seller holds to strict
per-deal monotonicity.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional
from core_buyer.hosted_settlement import HostedSettlementTransport

import typer
from rich.console import Console

console = Console()

HEARTBEAT_OPERATION = "deal_heartbeat"


def send_heartbeat(
    *,
    seller_url: str,
    deal_ref: str,
    principal,
    signer,
    seller_principal,
    resolve_seller_principals,
    status: str = "healthy",
) -> dict[str, Any]:
    """Send one v2 body-bound, principal-bound heartbeat."""
    from core_buyer.orchestration import _signed_json

    return _signed_json(
        f"{seller_url.rstrip('/')}/api/v1/deals/{deal_ref}/heartbeat",
        {
            "buyer_principal": principal.model_dump(mode="json"),
            "seller_principal": seller_principal.model_dump(mode="json"),
            "payload": {"schema": "vms.heartbeat.v1", "status": status},
        },
        signer=signer,
        principal=principal,
        method="POST",
        operation=HEARTBEAT_OPERATION,
        resource=deal_ref,
        timeout=60.0,
        resolve_response_principals=resolve_seller_principals,
    )


def _plan_heartbeat_interval(deal) -> Optional[float]:
    """The cadence the seller's plan asks for, when it asks."""
    plan = getattr(deal, "settlement_plan", None)
    if isinstance(plan, dict):
        hb = (plan.get("service_terms") or {}).get("heartbeat") or {}
        interval = hb.get("interval_seconds")
        if interval is not None:
            try:
                return float(interval)
            except (TypeError, ValueError):
                pass
    return None


def _deal_expiration_unix(deal) -> Optional[float]:
    """Best-available collect-vs-reclaim boundary for the deal."""
    plan = getattr(deal, "settlement_plan", None)
    if isinstance(plan, dict):
        for ob in plan.get("obligations") or []:
            exp = ob.get("expiration_unix")
            if exp is not None:
                try:
                    return float(exp)
                except (TypeError, ValueError):
                    pass


def _deal_seller_principal(deal):
    from market_identity import Identity

    plan = getattr(deal, "settlement_plan", None)
    if isinstance(plan, dict):
        for obligation in plan.get("obligations") or []:
            if not isinstance(obligation, dict):
                continue
            raw = obligation.get("claimant_principal")
            if raw is None:
                continue
            principal = Identity.model_validate(raw)
            if deal.publisher_principals.allows(principal):
                return principal
    raise ValueError("deal has no trusted claimant principal")


async def _service_loop(
    *,
    log,
    deal,
    signer,
    chain_settings=None,
    resolve_seller_principals,
    interval_seconds: float,
    once: bool,
    reclaim: bool,
) -> int:
    """Heartbeat until expiry (or once), then optionally reclaim.

    Returns the process exit code.
    """
    escrow_uid = deal.escrow_uid
    deal_ref = deal.settlement_ref or deal.escrow_uid
    expiration = _deal_expiration_unix(deal)
    beats = 0
    failures = 0

    seller_principal = _deal_seller_principal(deal)
    while True:
        now = time.time()
        if expiration is not None and now >= expiration:
            console.print(
                f"[yellow]deal expired[/yellow] (expiration_unix={int(expiration)})"
            )
            log.event("service_expired", escrow_uid=escrow_uid, heartbeats=beats)
            break
        try:
            ack = await asyncio.to_thread(
                send_heartbeat,
                seller_url=deal.seller_url,
                deal_ref=deal_ref,
                principal=deal.buyer_principal,
                signer=signer,
                seller_principal=seller_principal,
                resolve_seller_principals=resolve_seller_principals,
            )
            beats += 1
            failures = 0
            log.event(
                "heartbeat_sent",
                escrow_uid=escrow_uid,
                count=ack.get("heartbeat_count"),
            )
            console.print(
                f"heartbeat {ack.get('heartbeat_count')} acked "
                f"(next expected by {ack.get('next_expected_by_unix')})"
            )
        except Exception as exc:
            failures += 1
            log.event("heartbeat_failed", escrow_uid=escrow_uid, error=str(exc))
            console.print(f"[red]heartbeat failed[/red]: {exc}")
            if once:
                return 1
        if once:
            return 0
        # Sleep toward the next beat, but wake at expiration if sooner.
        delay = interval_seconds
        if expiration is not None:
            delay = max(0.0, min(delay, expiration - time.time()))
        await asyncio.sleep(delay)

    if not reclaim:
        return 0

    # Post-expiry: reclaim if the seller never collected. A revert here
    # normally means collection already happened — report, don't fail.
    if deal.settlement_ref:
        transport = HostedSettlementTransport(
            seller_url=deal.seller_url,
            principal=deal.buyer_principal,
            signer=signer,
            resolve_seller_principals=resolve_seller_principals,
        )
        result = await asyncio.to_thread(
            transport.reclaim,
            settlement_ref=deal.settlement_ref,
        )
        log.event(
            "hosted_settlement_reclaimed",
            settlement_ref=deal.settlement_ref,
            status=result.get("status"),
        )
        return 0

    from .escrow_cli import _do_reclaim

    console.print("attempting post-expiry EVM reclaim…")
    try:
        codec, receipt = await _do_reclaim(
            escrow_uid=deal.escrow_uid,
            private_key=chain_settings.buyer_private_key,
            rpc_url=chain_settings.rpc_url,
            chain_name=chain_settings.chain_name,
            addr_config_path=getattr(chain_settings, "alkahest_addr_config", None),
        )
        log.event("escrow_reclaimed", escrow_uid=deal.escrow_uid, codec=str(codec))
        console.print(f"[green]escrow reclaimed[/green] via {codec}")
    except Exception as exc:
        log.event("reclaim_skipped", escrow_uid=deal.escrow_uid, reason=str(exc))
        console.print(f"[yellow]reclaim not possible[/yellow]: {exc}")
    return 0


def register(app: typer.Typer) -> None:
    """Register the top-level `market service` command."""

    @app.command("service")
    def service(
        run_id: str = typer.Option(
            ...,
            "--from",
            "--run",
            "-r",
            help="Buyer run-id of a settled deal (see `market logs runs`).",
        ),
        interval: Optional[float] = typer.Option(
            None,
            "--interval",
            "-i",
            help="Heartbeat cadence in seconds. Default: the cadence the "
            "seller's settlement plan asks for, else 60.",
        ),
        once: bool = typer.Option(
            False,
            "--once",
            help="Send a single heartbeat and exit (0 on ack, 1 on failure).",
        ),
        reclaim: bool = typer.Option(
            True,
            "--reclaim/--no-reclaim",
            help="After expiry, attempt to reclaim the escrow if the "
            "seller never collected.",
        ),
        seller: Optional[str] = typer.Option(
            None,
            "--seller",
            help="Override the seller URL recorded in the run-log.",
        ),
    ) -> None:
        """Service a settled deal: heartbeat while healthy, reclaim on expiry."""
        from .common import chain_by_name, resolve_recovery_buyer_identity
        from .deal_helpers import (
            load_deal_context,
            make_deal_publisher_trust_resolver,
            resolve_chain_settings,
        )
        from .run_log import RunLog
        from .settle_cli import _accepted_proposal_chain, _first_listing_chain

        identity = resolve_recovery_buyer_identity(run_id)
        signer = identity.signer
        deal = load_deal_context(run_id, signer=signer)
        resolve_seller_principals = make_deal_publisher_trust_resolver(
            run_id, deal, signer
        )
        if seller:
            deal.seller_url = seller
        if not deal.escrow_uid and not deal.settlement_ref:
            console.print("[red]run-log has no settlement reference[/red]")
            raise typer.Exit(2)

        chain_settings = None
        if deal.escrow_uid:
            chain_name = _accepted_proposal_chain(deal) or _first_listing_chain(deal)
            chain_cfg = chain_by_name(chain_name)
            chain_settings = resolve_chain_settings(
                buyer_address=None,
                buyer_private_key=None,
                ssh_public_key=None,
                chain=chain_cfg,
                token_contract=deal.token_contract,
                token_decimals=(
                    int(deal.token_decimals)
                    if deal.token_decimals is not None
                    else None
                ),
                require_ssh=False,
            )

        effective_interval = (
            interval
            if interval is not None
            else (_plan_heartbeat_interval(deal) or 60.0)
        )

        log = RunLog.open(
            run_id,
            signer=signer,
            profile_id=identity.profile_id,
        )
        log.event(
            "service_started",
            escrow_uid=deal.escrow_uid,
            interval_seconds=effective_interval,
            once=once,
        )
        code = asyncio.run(
            _service_loop(
                log=log,
                deal=deal,
                signer=signer,
                resolve_seller_principals=resolve_seller_principals,
                chain_settings=chain_settings,
                interval_seconds=effective_interval,
                once=once,
                reclaim=reclaim and not once,
            )
        )
        raise typer.Exit(code)
