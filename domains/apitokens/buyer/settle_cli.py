"""`market tokens settle` — composite stages 3-5 of a token deal.

Resumes a buy from the post-negotiation point: creates the on-chain
escrow if not already created, POSTs `/settle/{escrow_uid}` to the
seller, polls until terminal, and delivers the issued credentials to
the run-log. Driven by a buyer run-log produced by `market tokens
negotiate` (or a partially-completed `market tokens buy`).

Token deals are durationless: escrow terms materialize with
``duration_seconds=0`` and the settle request carries an empty
``ssh_public_key`` (the VM domain's provisioning payload).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core_buyer.deal_helpers import load_deal_context, open_run_log
from core_buyer.orchestration import (
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
    submit_settlement,
    wait_for_settlement,
)
from core_buyer.run_log import read_run


def _chain_name_from_run_log(run_id: str) -> Optional[str]:
    """Look up the chain the deal targets, from the run-log."""
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


def _accepted_proposal_chain(deal) -> Optional[str]:
    terms = getattr(deal, "accepted_escrow_terms", None)
    if isinstance(terms, list) and terms:
        first = terms[0]
        if isinstance(first, dict):
            chain = first.get("chain_name")
            if isinstance(chain, str) and chain:
                return chain
    proposal = getattr(deal, "accepted_escrow_proposal", None)
    if isinstance(proposal, dict):
        chain = proposal.get("chain_name")
        if isinstance(chain, str) and chain:
            return chain
    return None


def render_credentials(console: Console, credentials: dict) -> None:
    """Show the issued key once — the secret is never returned again.

    The same credentials are appended to the run-log
    (``credentials_delivered``), which is the buyer's durable copy.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    for label, key in (
        ("Key ID", "key_id"),
        ("Secret", "secret"),
        ("Base URL", "base_url"),
        ("Balance", "balance"),
    ):
        if credentials.get(key) is not None:
            table.add_row(label, str(credentials[key]))
    console.print(Panel(
        table,
        title="API key issued — shown once; saved to the run-log",
        border_style="green",
    ))


def run_settle_from_log(
    *,
    run_id: str,
    escrow_uid: Optional[str],
    buyer_address: Optional[str],
    buyer_private_key: Optional[str],
    chain_name: Optional[str],
    poll_interval: float,
    settlement_timeout: float,
    console: Optional[Console] = None,
) -> dict:
    """Drive stages 3-5 of a token deal from a buyer run-log.

    Reusable by both ``market tokens settle`` and ``market tokens buy
    --from``. Reads the run-log for ``run_id``, creates the on-chain
    escrow if not already present, POSTs ``/settle/{escrow_uid}`` to
    the seller, and polls until terminal. Logs each stage transition —
    including the issued credentials — back into the same run-log.

    Returns the final settle-status body. Raises ``typer.Exit`` on
    fatal errors.
    """
    console = console or Console()
    deal = load_deal_context(run_id)

    from .common import chain_by_name, resolve_buyer_wallet
    chain_cfg_name = (
        chain_name
        or _accepted_proposal_chain(deal)
        or _chain_name_from_run_log(run_id)
    )
    if not chain_cfg_name:
        typer.secho(
            "Could not determine the chain from the run-log or deal context. "
            "Pass --chain to specify which configured chain to settle on.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain_cfg = chain_by_name(chain_cfg_name)

    if deal.accepted_escrow_proposal is None and deal.accepted_escrow_terms is None:
        typer.secho(
            "Run-log carries no seller-accepted escrow proposal. Re-run "
            "negotiation so the accepted proposal is captured — token "
            "settlement always settles the seller-confirmed shape.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    resolved_buyer_address, resolved_buyer_private_key = resolve_buyer_wallet(
        override_addr=buyer_address,
        override_pk=buyer_private_key,
    )
    if not resolved_buyer_private_key:
        typer.secho(
            "Missing required config: wallet.private_key",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain = SimpleNamespace(
        buyer_address=resolved_buyer_address,
        buyer_private_key=resolved_buyer_private_key,
        rpc_url=chain_cfg.rpc_url,
        chain_name=chain_cfg.name,
        alkahest_addr_config=chain_cfg.alkahest_address_config_path,
    )

    log = open_run_log(run_id)
    log.event("settle_resumed", run_id=run_id)

    resolved_uid = escrow_uid or deal.escrow_uid

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", run_id)
    header.add_row("Seller", deal.seller_url)
    header.add_row("Negotiation", deal.negotiation_id)
    header.add_row("Agreed amount (total)", str(deal.agreed_amount))
    if resolved_uid:
        header.add_row("Escrow UID", resolved_uid + " (skip create)")
    console.print(Panel(header, title="market tokens settle", border_style="cyan"))

    # --- Stage 3: escrow.create (skip if uid already known) -------
    if not resolved_uid:
        from market_alkahest.schemas import EscrowProposal, EscrowTerms
        from core_buyer.escrow_client import (
            make_buyer_payment_escrow_terms_fn,
            make_create_escrow_fn,
        )

        log.event("escrow_create_start", terms={
            "seller_url": deal.seller_url,
            "listing_id": deal.listing_id,
            "negotiation_id": deal.negotiation_id,
            "agreed_amount": deal.agreed_amount,
            "duration_seconds": 0,
        })
        console.print("[dim]escrow.create[/dim]  approve + create on-chain…")

        if deal.accepted_escrow_terms is not None:
            escrow_terms_list = [
                EscrowTerms.model_validate(item)
                for item in deal.accepted_escrow_terms
            ]
        else:
            proposal = EscrowProposal(**deal.accepted_escrow_proposal)
            build_terms = make_buyer_payment_escrow_terms_fn(
                chain_name=chain.chain_name,
                addr_config_path=chain.alkahest_addr_config,
            )
            escrow_terms_list = build_terms(
                proposal,
                deal.seller_wallet_address,
                float(deal.agreed_amount),
                0,  # token deals fund a quantity, not a lease
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
        log.event("escrow_created", escrow_uid=resolved_uid, chain_name=chain.chain_name)
        console.print(f"[green]escrow created[/green]  {resolved_uid}")

    # --- Stage 4: submit settlement -------------------------------
    try:
        submit_body = submit_settlement(
            seller_url=deal.seller_url,
            escrow_uid=resolved_uid,
            negotiation_id=deal.negotiation_id,
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
    credentials = final.get("tenant_credentials")
    if isinstance(credentials, dict) and credentials:
        # The durable copy — the seller returns the secret exactly once.
        log.event("credentials_delivered", credentials=credentials)
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
    if final.get("reason"):
        result.add_row("Reason", str(final["reason"]))
    border = "green" if final.get("status") == "ready" else "yellow"
    console.print(Panel(result, title="Settlement complete", border_style=border))

    if isinstance(credentials, dict) and credentials:
        render_credentials(console, credentials)

    if final.get("status") != "ready":
        raise typer.Exit(7)

    return final


def register(tokens_app: typer.Typer) -> None:
    """Register `market tokens settle`."""

    @tokens_app.command("settle")
    def settle(
        run_id: str = typer.Option(
            ..., "--from", "--run", "-r",
            help="Buyer run-id from a prior `market tokens negotiate` to "
                 "resume from (see the buy-runs log directory).",
        ),
        escrow_uid: Optional[str] = typer.Option(
            None, "--escrow-uid", "-u",
            help="Skip escrow.create when the on-chain escrow already exists. "
                 "If absent, the run-log is checked for an `escrow_created` event.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet address (default: derived from wallet.private_key).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        chain_name: Optional[str] = typer.Option(
            None, "--chain",
            help="Override which configured [chains.<name>] entry to settle on. "
                 "When omitted, reads chain_name from the accepted proposal "
                 "or escrow_created event.",
        ),
        poll_interval: float = typer.Option(
            DEFAULT_SETTLEMENT_POLL_INTERVAL, "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            DEFAULT_SETTLEMENT_TIMEOUT, "--settlement-timeout",
            help="Max seconds to wait for issuance before giving up.",
        ),
    ) -> None:
        """Resume a token buy from the post-negotiation point.

        Reads the buyer run-log for `<run_id>`, creates the on-chain
        escrow if not already present, POSTs `/settle/{escrow_uid}` to
        the seller, and polls until terminal. The issued credentials
        land in the same run-log (``credentials_delivered``) — the
        seller returns the secret exactly once.

        Requires the run-log to contain an `agreed` negotiation outcome.
        """
        run_settle_from_log(
            run_id=run_id,
            escrow_uid=escrow_uid,
            buyer_address=buyer_address,
            buyer_private_key=buyer_private_key,
            chain_name=chain_name,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
        )
