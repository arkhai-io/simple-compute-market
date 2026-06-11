"""`market service` — the buyer-side deal servicing engine.

The buyer half of lifecycle work item I.3: after `settle` hands over a
running VM, someone on the buyer's side must keep the deal serviced —
emit signed heartbeats while the service is healthy (the seller's
evidence for heartbeat-gated collection), stop when it is not, and
reclaim the escrow if it expires uncollected. `market service --from
<run_id>` is that engine: a foreground loop over the same run-log the
buy/settle stages share, restartable at any point.

Heartbeats are signed exactly like every other buyer request
(`deal_heartbeat:<escrow_uid>:<ts>`, EIP-191); the timestamp doubles as
the heartbeat's claimed send time, which the seller holds to strict
per-deal monotonicity.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import typer
from rich.console import Console

console = Console()

HEARTBEAT_OPERATION = "deal_heartbeat"


def send_heartbeat(
    *,
    seller_url: str,
    escrow_uid: str,
    buyer_address: str,
    buyer_private_key: str,
    status: str = "healthy",
) -> dict[str, Any]:
    """Sign and POST one heartbeat; returns the seller's ack body."""
    from .buyer_client import _post, _sign

    sig, ts = _sign(f"{HEARTBEAT_OPERATION}:{escrow_uid}", buyer_private_key)
    return _post(
        f"{seller_url.rstrip('/')}/api/v1/deals/{escrow_uid}/heartbeat",
        {
            "buyer_address": buyer_address,
            "payload": {"schema": "vms.heartbeat.v1", "status": status},
        },
        signature=sig,
        timestamp=ts,
        identity_identifier=buyer_address,
    )


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
    return None


async def _service_loop(
    *,
    log,
    deal,
    chain_settings,
    interval_seconds: float,
    once: bool,
    reclaim: bool,
) -> int:
    """Heartbeat until expiry (or once), then optionally reclaim.

    Returns the process exit code.
    """
    escrow_uid = deal.escrow_uid
    expiration = _deal_expiration_unix(deal)
    beats = 0
    failures = 0

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
                escrow_uid=escrow_uid,
                buyer_address=chain_settings.buyer_address,
                buyer_private_key=chain_settings.buyer_private_key,
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
    from .escrow_cli import _do_reclaim

    console.print("attempting post-expiry reclaim…")
    try:
        codec, receipt = await _do_reclaim(
            escrow_uid=escrow_uid,
            private_key=chain_settings.buyer_private_key,
            rpc_url=chain_settings.rpc_url,
            chain_name=chain_settings.chain_name,
            addr_config_path=getattr(chain_settings, "alkahest_addr_config", None),
        )
        log.event("escrow_reclaimed", escrow_uid=escrow_uid, codec=str(codec))
        console.print(f"[green]escrow reclaimed[/green] via {codec}")
    except Exception as exc:
        log.event("reclaim_skipped", escrow_uid=escrow_uid, reason=str(exc))
        console.print(
            f"[yellow]reclaim not possible[/yellow] "
            f"(usually: the seller already collected): {exc}"
        )
    return 0


def register(app: typer.Typer) -> None:
    """Register the top-level `market service` command."""

    @app.command("service")
    def service(
        run_id: str = typer.Option(
            ..., "--from", "--run", "-r",
            help="Buyer run-id of a settled deal (see `market logs runs`).",
        ),
        interval: float = typer.Option(
            60.0, "--interval", "-i",
            help="Heartbeat cadence in seconds.",
        ),
        once: bool = typer.Option(
            False, "--once",
            help="Send a single heartbeat and exit (0 on ack, 1 on failure).",
        ),
        reclaim: bool = typer.Option(
            True, "--reclaim/--no-reclaim",
            help="After expiry, attempt to reclaim the escrow if the "
                 "seller never collected.",
        ),
        seller: Optional[str] = typer.Option(
            None, "--seller",
            help="Override the seller URL recorded in the run-log.",
        ),
    ) -> None:
        """Service a settled deal: heartbeat while healthy, reclaim on expiry."""
        from .common import chain_by_name
        from .deal_helpers import load_deal_context, resolve_chain_settings
        from .run_log import RunLog
        from .settle_cli import _accepted_proposal_chain, _first_listing_chain

        deal = load_deal_context(run_id)
        if seller:
            deal.seller_url = seller
        if not deal.escrow_uid:
            console.print(
                "[red]run-log has no escrow_uid[/red] — settle the deal first "
                "(`market settle --from ...`)."
            )
            raise typer.Exit(2)

        chain_name = _accepted_proposal_chain(deal) or _first_listing_chain(deal)
        chain_cfg = chain_by_name(chain_name)
        chain_settings = resolve_chain_settings(
            buyer_address=None,
            buyer_private_key=None,
            ssh_public_key=None,
            chain=chain_cfg,
            token_contract=deal.token_contract,
            token_decimals=(
                int(deal.token_decimals) if deal.token_decimals is not None else None
            ),
            require_ssh=False,
        )

        log = RunLog.open(run_id)
        log.event(
            "service_started",
            escrow_uid=deal.escrow_uid,
            interval_seconds=interval,
            once=once,
        )
        code = asyncio.run(
            _service_loop(
                log=log,
                deal=deal,
                chain_settings=chain_settings,
                interval_seconds=interval,
                once=once,
                reclaim=reclaim and not once,
            )
        )
        raise typer.Exit(code)
