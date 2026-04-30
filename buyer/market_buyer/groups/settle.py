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


def register(app: typer.Typer) -> None:
    """Register the top-level `market settle` command."""

    @app.command("settle")
    def settle(
        run_id: str = typer.Option(
            ..., "--run", "-r",
            help="Buyer run-id from a prior `market negotiate` (see `market logs runs`).",
        ),
        escrow_uid: Optional[str] = typer.Option(
            None, "--escrow-uid", "-u",
            help="Skip escrow.create when the on-chain escrow already exists. "
                 "If absent, the run-log is checked for an `escrow_created` event.",
        ),
        token_contract: Optional[str] = typer.Option(
            None, "--token-contract",
            help="ERC-20 contract address. Default: resolve 'MOCK' via the token registry.",
        ),
        token_decimals: int = typer.Option(
            18, "--token-decimals",
            help="ERC-20 token decimals.",
        ),
        duration_hours: Optional[int] = typer.Option(
            None, "--duration-hours", "-t",
            help="Lease duration the escrow funds. Default: from the run-log "
                 "if recorded, else 1.",
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
        rpc_url: Optional[str] = typer.Option(
            None, "--rpc-url",
            help="Chain RPC URL (default: chain.rpc_url).",
        ),
        chain_name: Optional[str] = typer.Option(
            None, "--chain-name",
            help="Chain name for alkahest address resolution (default: chain.name).",
        ),
        alkahest_addr_config: Optional[str] = typer.Option(
            None, "--alkahest-addr-config",
            help="Path to alkahest address config JSON (default: chain.alkahest_address_config_path).",
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
        """
        console = Console()
        deal = load_deal_context(run_id)
        # Run-log enrichments (when `market negotiate` was given the
        # corresponding flags) become defaults if the operator didn't
        # pass them on `settle`. Explicit flags still win.
        effective_token = token_contract or deal.token_contract
        effective_token_decimals = (
            token_decimals if token_decimals != 18 else (deal.token_decimals or 18)
        )
        chain = resolve_chain_settings(
            buyer_address=buyer_address,
            buyer_private_key=buyer_private_key,
            ssh_public_key=ssh_public_key,
            rpc_url=rpc_url,
            chain_name=chain_name,
            alkahest_addr_config=alkahest_addr_config,
            token_contract=effective_token,
            token_decimals=effective_token_decimals,
        )

        log = open_run_log(run_id)
        log.event("settle_resumed", run_id=run_id)

        # Apply --escrow-uid override or fall back to run-log.
        resolved_uid = escrow_uid or deal.escrow_uid
        effective_duration = (
            duration_hours if duration_hours is not None else deal.duration_hours
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_id)
        header.add_row("Seller", deal.seller_url)
        header.add_row("Negotiation", deal.negotiation_id)
        header.add_row("Agreed price", str(deal.agreed_price))
        header.add_row("Duration (hours)", str(effective_duration))
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
                agreed_price=deal.agreed_price,
                duration_hours=effective_duration,
            )
            log.event("escrow_create_start", terms=terms.__dict__)
            console.print("[dim]escrow.create[/dim]  approve + create on-chain…")

            from ..escrow_client import make_create_escrow_fn
            create_escrow = make_create_escrow_fn(
                private_key=chain.buyer_private_key,
                rpc_url=chain.rpc_url,
                chain_name=chain.chain_name,
                addr_config_path=chain.alkahest_addr_config,
                token_contract_address=chain.token_contract,
                token_decimals=chain.token_decimals,
                expiration_seconds=expiration_seconds,
            )
            try:
                resolved_uid = create_escrow(terms)
            except Exception as exc:
                log.event("escrow_create_failed", error=str(exc))
                log.end("error", error=f"escrow_create: {exc}")
                typer.secho(
                    f"escrow.create failed on-chain: {exc}",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(4) from exc
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
            attestation_uid=final.get("attestation_uid"),
        )

        result = Table.grid(padding=(0, 2))
        result.add_column(style="bold")
        result.add_column()
        result.add_row("Status", str(final.get("status")))
        result.add_row("Escrow UID", resolved_uid)
        if final.get("attestation_uid"):
            result.add_row("Attestation UID", str(final["attestation_uid"]))
        if final.get("connection_details"):
            result.add_row("Connection", str(final["connection_details"]))
        if final.get("reason"):
            result.add_row("Reason", str(final["reason"]))
        border = "green" if final.get("status") == "ready" else "yellow"
        console.print(Panel(result, title="Settlement complete", border_style=border))

        if final.get("status") != "ready":
            raise typer.Exit(7)
