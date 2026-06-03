"""`market settle` — composite stages 3-5 of a deal.

Resumes a buy from the post-negotiation point: creates the on-chain
escrow if not already created, POSTs `/settle/{escrow_uid}` to the
seller, polls until terminal. Driven by a buyer run-log produced by
`market negotiate` (or a partially-completed `market buy`).

Composite by design — for the rare cases where you want only stage 3
(escrow.create) without involving the seller, use
`market escrow create --run <id>`.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..buy_orchestrator import (
    AgreedTerms,
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
    _resolve_seller_wallet,
    submit_settlement,
    wait_for_settlement,
)
from ._deal import load_deal_context, open_run_log, resolve_chain_settings
from ..run_log import read_run


def _chain_name_from_run_log(run_id: str) -> Optional[str]:
    """Look up the chain the deal targets, from the run-log.

    Source priority:
      1. ``escrow_created`` event (recorded at escrow creation time).
      2. ``run_started`` event (recorded when ``market negotiate`` picked
         the chain from the listing's accepted_escrows).

    Settling on a different chain would fail, so we trust whichever
    event the buyer wrote first.
    """
    for ev in read_run(run_id):
        if ev.get("event") == "escrow_created":
            cn = ev.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
            terms = ev.get("terms") or {}
            cn = terms.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
        if ev.get("event") == "run_started":
            cn = ev.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
    return None


def _first_listing_chain(deal) -> Optional[str]:
    """Fallback: pick the chain from the deal's listing accepted_escrows."""
    listing = getattr(deal, "listing", None)
    if isinstance(listing, dict):
        for entry in listing.get("accepted_escrows") or []:
            if isinstance(entry, dict):
                cn = entry.get("chain_name")
                if isinstance(cn, str) and cn:
                    return cn
    return None


def run_settle_from_log(
    *,
    run_id: str,
    escrow_uid: Optional[str],
    token_contract: Optional[str],
    token_decimals: Optional[int],
    duration_seconds: Optional[int],
    expiration_seconds: int,
    ssh_public_key: Optional[str],
    buyer_address: Optional[str],
    buyer_private_key: Optional[str],
    chain_name: Optional[str],
    poll_interval: float,
    settlement_timeout: float,
    console: Optional[Console] = None,
) -> dict:
    """Drive stages 3-5 of a deal from a buyer run-log.

    Reusable by both ``market settle`` and ``market buy --from``.
    Reads the run-log for ``run_id``, creates the on-chain escrow if
    not already present, POSTs ``/settle/{escrow_uid}`` to the seller,
    and polls until terminal. Logs each stage transition back into
    the same run-log.

    Returns the final settle-status body. Raises ``typer.Exit`` on
    fatal errors (resolution failures, on-chain failures, polling
    timeout, non-``ready`` terminal status).
    """
    console = console or Console()
    deal = load_deal_context(run_id)
    effective_token = token_contract or deal.token_contract
    # Precedence: explicit --token-decimals override > value recorded in
    # the run-log during the original buy > chain decimals() lookup
    # (delegated to resolve_chain_settings when this is None). The old
    # fallback to 18 silently produced wrong escrow amounts for non-18-
    # decimal tokens (USDC = 6).
    effective_token_decimals: Optional[int] = (
        int(token_decimals)
        if token_decimals is not None
        else (int(deal.token_decimals) if deal.token_decimals is not None else None)
    )
    from ..common import chain_by_name
    chain_cfg_name = chain_name or _chain_name_from_run_log(run_id) or _first_listing_chain(deal)
    if not chain_cfg_name:
        typer.secho(
            "Could not determine the chain from the run-log or deal context. "
            "Pass --chain to specify which configured chain to settle on.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain_cfg = chain_by_name(chain_cfg_name)
    chain = resolve_chain_settings(
        buyer_address=buyer_address,
        buyer_private_key=buyer_private_key,
        ssh_public_key=ssh_public_key,
        chain=chain_cfg,
        token_contract=effective_token,
        token_decimals=effective_token_decimals,
    )

    log = open_run_log(run_id)
    log.event("settle_resumed", run_id=run_id)

    resolved_uid = escrow_uid or deal.escrow_uid
    effective_duration = (
        duration_seconds if duration_seconds is not None else deal.duration_seconds
    )

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", run_id)
    header.add_row("Seller", deal.seller_url)
    header.add_row("Negotiation", deal.negotiation_id)
    header.add_row("Agreed price (per hour)", str(deal.agreed_amount))
    header.add_row("Duration (seconds)", str(effective_duration))
    header.add_row("Token", f"{chain.token_contract} (decimals={chain.token_decimals})")
    if resolved_uid:
        header.add_row("Escrow UID", resolved_uid + " (skip create)")
    console.print(Panel(header, title="market settle", border_style="cyan"))

    # --- Stage 3: escrow.create (skip if uid already known) -------
    if not resolved_uid:
        seller_wallet = deal.seller_wallet_address
        if not seller_wallet:
            try:
                seller_wallet = _resolve_seller_wallet(deal.seller_url)
            except RuntimeError as exc:
                log.event("escrow_resolve_wallet_failed", error=str(exc))
                log.end("error", error=f"resolve_seller_wallet: {exc}")
                typer.secho(
                    f"Could not resolve seller wallet from "
                    f"{deal.seller_url}/.well-known/agent-wallet.json: {exc}",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(3)

        terms = AgreedTerms(
            seller_url=deal.seller_url,
            seller_wallet_address=seller_wallet,
            negotiation_id=deal.negotiation_id,
            listing_id=deal.listing_id,
            agreed_amount=deal.agreed_amount,
            duration_seconds=effective_duration,
        )
        log.event("escrow_create_start", terms=terms.__dict__)
        console.print("[dim]escrow.create[/dim]  approve + create on-chain…")

        # Synthesize the EscrowProposal that `market negotiate` would have
        # sent (and the seller echoed back). The run-log doesn't currently
        # carry the seller-confirmed proposal, so we rebuild it from chain
        # config — matches what the storefront's accepted_escrows uses for
        # the default ERC20 non-tierable contract.
        import time as _time
        from service.schemas import EscrowProposal
        from service.clients.alkahest import (
            get_erc20_escrow_obligation_nontierable,
        )
        from ..escrow_client import (
            make_buyer_payment_escrow_terms_fn,
            make_create_escrow_fn,
        )

        escrow_address = get_erc20_escrow_obligation_nontierable(
            chain.chain_name,
            config_path=chain.alkahest_addr_config or None,
        )
        proposal = EscrowProposal(
            chain_name=chain.chain_name,
            escrow_address=escrow_address,
            fields={"token": chain.token_contract},
            literal_fields={"token": chain.token_contract},
            expiration_unix=int(_time.time()) + expiration_seconds,
        )

        build_terms = make_buyer_payment_escrow_terms_fn(
            chain_name=chain.chain_name,
            addr_config_path=chain.alkahest_addr_config,
        )
        escrow_terms_list = build_terms(
            proposal,
            seller_wallet,
            float(deal.agreed_amount),
            int(effective_duration),
        )

        create_escrow = make_create_escrow_fn(
            private_key=chain.buyer_private_key,
            rpc_url=chain.rpc_url,
            chain_name=chain.chain_name,
            addr_config_path=chain.alkahest_addr_config,
        )
        try:
            uids = create_escrow(escrow_terms_list)
        except Exception as exc:
            log.event("escrow_create_failed", error=str(exc))
            log.end("error", error=f"escrow_create: {exc}")
            typer.secho(
                f"escrow.create failed on-chain: {exc}",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(4) from exc
        if not uids:
            log.event("escrow_create_failed", error="no uid returned")
            log.end("error", error="escrow_create: no uid returned")
            typer.secho(
                "escrow.create returned no uid — buyer terms list was empty.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(4)
        resolved_uid = uids[0]
        log.event("escrow_created", escrow_uid=resolved_uid)
        console.print(f"[green]escrow created[/green]  {resolved_uid}")

    # --- Stage 4: submit settlement -------------------------------
    try:
        submit_body = submit_settlement(
            seller_url=deal.seller_url,
            escrow_uid=resolved_uid,
            negotiation_id=deal.negotiation_id,
            ssh_public_key=chain.ssh_public_key,
            buyer_address=chain.buyer_address,
            buyer_private_key=chain.buyer_private_key,
            chain_name=chain.chain_name,
        )
    except RuntimeError as exc:
        log.event("settle_submit_failed", error=str(exc))
        log.end("error", error=f"settle_submit: {exc}")
        typer.secho(f"/settle submit failed: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(5) from exc
    log.event("settle_submitted", body=submit_body)
    console.print(f"[dim]submitted[/dim]  initial body={submit_body}")

    # --- Stage 5: poll status until terminal ----------------------
    def _on_poll(attempt: int, body: dict) -> None:
        log.event("settle_status", attempt=attempt, body=body)

    try:
        final = wait_for_settlement(
            seller_url=deal.seller_url,
            escrow_uid=resolved_uid,
            buyer_address=chain.buyer_address,
            buyer_private_key=chain.buyer_private_key,
            poll_interval=poll_interval,
            total_timeout=settlement_timeout,
            on_poll=_on_poll,
        )
    except TimeoutError as exc:
        log.event("settle_terminal", status="timeout", error=str(exc))
        log.end("timeout", escrow_uid=resolved_uid, error=str(exc))
        typer.secho(f"settlement polling timed out: {exc}", err=True, fg=typer.colors.YELLOW)
        raise typer.Exit(6) from exc

    log.event("settle_terminal", body=final)
    log.end(
        final.get("status") or "unknown",
        escrow_uid=resolved_uid,
        fulfillment_uid=final.get("fulfillment_uid"),
    )

    result = Table.grid(padding=(0, 2))
    result.add_column(style="bold")
    result.add_column()
    result.add_row("Status", str(final.get("status")))
    result.add_row("Escrow UID", resolved_uid)
    if final.get("fulfillment_uid"):
        result.add_row("Fulfillment UID", str(final["fulfillment_uid"]))
    if final.get("connection_details"):
        result.add_row("Connection", str(final["connection_details"]))
    if final.get("reason"):
        result.add_row("Reason", str(final["reason"]))
    border = "green" if final.get("status") == "ready" else "yellow"
    console.print(Panel(result, title="Settlement complete", border_style=border))

    if final.get("status") != "ready":
        raise typer.Exit(7)

    return final


def register(app: typer.Typer) -> None:
    """Register the top-level `market settle` command."""

    @app.command("settle")
    def settle(
        run_id: str = typer.Option(
            ..., "--from", "--run", "-r",
            help="Buyer run-id from a prior `market negotiate` to resume "
                 "from (see `market logs runs`).",
        ),
        escrow_uid: Optional[str] = typer.Option(
            None, "--escrow-uid", "-u",
            help="Skip escrow.create when the on-chain escrow already exists. "
                 "If absent, the run-log is checked for an `escrow_created` event.",
        ),
        token_contract: Optional[str] = typer.Option(
            None, "--token-contract",
            help="ERC-20 payment token. Optional override — defaults to the "
                 "token recorded in the deal/run-log.",
        ),
        token_decimals: Optional[int] = typer.Option(
            None, "--token-decimals",
            help="ERC-20 token decimals override. When omitted, reads "
                 "the value recorded in the run-log; if that's also "
                 "missing, falls back to a chain decimals() lookup.",
        ),
        duration_hours: Optional[float] = typer.Option(
            None, "--duration-hours", "-t",
            help="Override the lease duration the escrow funds (hours, fractional ok). "
                 "Default: from the run-log if recorded.",
        ),
        expiration_seconds: int = typer.Option(
            3600, "--expiration",
            help="Escrow deadline (seconds from now) for the reclaim_expired escape hatch.",
        ),
        ssh_public_key: Optional[str] = typer.Option(
            None, "--ssh-public-key",
            help="SSH public key for provisioning (default: wallet.ssh_public_key).",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet (default: wallet.address from config.toml).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        chain_name: Optional[str] = typer.Option(
            None, "--chain",
            help="Override which configured [chains.<name>] entry to settle on. "
                 "When omitted, reads chain_name from the run-log's escrow_created "
                 "event; falls back to the first listing.accepted_escrows entry.",
        ),
        poll_interval: float = typer.Option(
            DEFAULT_SETTLEMENT_POLL_INTERVAL, "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            DEFAULT_SETTLEMENT_TIMEOUT, "--settlement-timeout",
            help="Max seconds to wait for provisioning before giving up.",
        ),
    ) -> None:
        """Resume a buy from the post-negotiation point.

        Reads the buyer run-log for `<run_id>`, creates the on-chain
        escrow if not already present, POSTs `/settle/{escrow_uid}` to
        the seller, and polls until terminal. Logs each stage transition
        back into the same run-log so a future `market logs show <id>`
        captures the full deal history.

        Requires the run-log to contain an `agreed` negotiation outcome.
        For mid-negotiation resume use `market buy --from <id>` instead.
        """
        # Convert user-friendly hours flag to the wire's seconds.
        duration_seconds_override = (
            int(round(duration_hours * 3600)) if duration_hours is not None else None
        )
        run_settle_from_log(
            run_id=run_id,
            escrow_uid=escrow_uid,
            token_contract=token_contract,
            token_decimals=token_decimals,
            duration_seconds=duration_seconds_override,
            expiration_seconds=expiration_seconds,
            ssh_public_key=ssh_public_key,
            buyer_address=buyer_address,
            buyer_private_key=buyer_private_key,
            chain_name=chain_name,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
        )
