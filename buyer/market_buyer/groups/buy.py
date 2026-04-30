"""`market buy` — pure-client sequential buy.

No buyer agent, no event pipeline. Drives the deal end-to-end from the
CLI process:

    discover (registry) →
    negotiate each match (sync HTTP rounds) →
    pick agreed match →
    create escrow on-chain (alkahest-py in-process) →
    POST /settle/{uid} on seller →
    poll /settle/{uid}/status until ready/failed.

The orchestrator itself is in market.buy_orchestrator; this command
just wires env → config → call.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..buy_orchestrator import (
    BuyConfig,
    BuyConstraints,
    run_buy,
)
from ..buyer_client import ResumeState, negotiate_with_seller
from ..common import resolve_config_value
from ..run_log import RunLog
from ._deal import (
    is_negotiation_complete,
    load_negotiation_resume_point,
    open_run_log,
)
from .settle import run_settle_from_log


def _run_resume_from(
    *,
    from_run: str,
    max_price: Optional[int],
    buyer_address: Optional[str],
    buyer_private_key: Optional[str],
    ssh_public_key: Optional[str],
    token_contract: Optional[str],
    token_decimals: int,
    rpc_url: Optional[str],
    chain_name: Optional[str],
    alkahest_addr_config: Optional[str],
    expiration_seconds: int,
    max_rounds: int,
    poll_interval: float,
    settlement_timeout: float,
    console: Console,
) -> None:
    """Composite resume: finish negotiation if mid-stream, then settle.

    The same run-log is appended throughout — fresh `negotiate`-style
    events when finishing the negotiation, then `settle_*` events from
    ``run_settle_from_log``.
    """
    if not is_negotiation_complete(from_run):
        if max_price is None:
            typer.secho(
                "--max-price is required when resuming a mid-stream "
                "negotiation (the strategy needs the buyer's ceiling).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        addr = resolve_config_value(
            override=buyer_address, toml_path="wallet.address",
        )
        pk = resolve_config_value(
            override=buyer_private_key, toml_path="wallet.private_key",
        )
        if not addr or not pk:
            typer.secho(
                "Missing buyer wallet config. Pass --buyer-address + "
                "--buyer-priv-key or set wallet.address + "
                "wallet.private_key in config.toml.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        resume_point = load_negotiation_resume_point(from_run)
        run_log = open_run_log(from_run)
        run_log.event(
            "negotiation_resumed",
            from_run=from_run,
            negotiation_id=resume_point.negotiation_id,
            rounds_completed=resume_point.rounds_completed,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", from_run)
        header.add_row("Mode", "resume (mid-negotiation)")
        header.add_row("Seller", resume_point.seller_url)
        header.add_row("Listing", resume_point.listing_id)
        header.add_row("Negotiation", resume_point.negotiation_id)
        header.add_row("Rounds completed", str(resume_point.rounds_completed))
        header.add_row("Ceiling", str(max_price))
        console.print(Panel(header, title="market buy --from", border_style="cyan"))

        def _observe(round_idx: int, our_msg: dict, reply: dict) -> None:
            run_log.event(
                "negotiation_round",
                round=round_idx,
                our_message=our_msg,
                their_reply=reply,
            )
            their = reply or {}
            console.print(
                f"[dim]  round {round_idx}[/dim]  → "
                f"{their.get('action', '-')} @ {their.get('price', '-')}"
            )

        try:
            outcome = negotiate_with_seller(
                seller_url=resume_point.seller_url,
                buyer_address=addr,
                buyer_private_key=pk,
                listing_id=resume_point.listing_id,
                initial_price=0,
                max_price=max_price,
                max_rounds=max_rounds,
                on_round=_observe,
                resume=ResumeState(
                    negotiation_id=resume_point.negotiation_id,
                    transcript=resume_point.transcript,
                    last_seller_price=resume_point.last_seller_price,
                    rounds_completed=resume_point.rounds_completed,
                ),
            )
        except RuntimeError as exc:
            run_log.event("negotiation_failed", error=str(exc))
            run_log.end("error", error=str(exc))
            typer.secho(f"Resumed negotiation failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        run_log.event(
            "negotiation_completed",
            seller_url=resume_point.seller_url,
            status=outcome.status,
            agreed_price=outcome.agreed_price,
            rounds=outcome.rounds,
            reason=outcome.reason,
            negotiation_id=outcome.negotiation_id,
            listing_id=resume_point.listing_id,
        )

        if outcome.status != "agreed" or outcome.agreed_price is None:
            run_log.end(
                outcome.status,
                negotiation_id=outcome.negotiation_id,
                rounds=outcome.rounds,
                reason=outcome.reason,
            )
            color = "yellow" if outcome.status == "exited" else "red"
            typer.secho(
                f"Negotiation did not agree (status={outcome.status}, "
                f"reason={outcome.reason!r}). Settlement skipped.",
                err=True, fg=getattr(typer.colors, color.upper(), typer.colors.YELLOW),
            )
            raise typer.Exit(4)

        console.print(
            f"[green]negotiation agreed[/green]  price={outcome.agreed_price} "
            f"rounds={outcome.rounds}"
        )

    run_settle_from_log(
        run_id=from_run,
        escrow_uid=None,
        token_contract=token_contract,
        token_decimals=token_decimals,
        duration_seconds=None,
        expiration_seconds=expiration_seconds,
        ssh_public_key=ssh_public_key,
        buyer_address=buyer_address,
        buyer_private_key=buyer_private_key,
        rpc_url=rpc_url,
        chain_name=chain_name,
        alkahest_addr_config=alkahest_addr_config,
        poll_interval=poll_interval,
        settlement_timeout=settlement_timeout,
        console=console,
    )


def register(app: typer.Typer) -> None:
    """Register the top-level `market buy` command."""

    @app.command("buy")
    def buy(
        initial_price: Optional[int] = typer.Option(
            None, "--initial-price",
            help="Opening bid per negotiation (raw token units). "
                 "Required for fresh runs; resumed runs (--from) "
                 "carry it forward from the run-log.",
        ),
        max_price: Optional[int] = typer.Option(
            None, "--max-price",
            help="Ceiling per negotiation (raw token units). Required "
                 "for fresh runs; required for --from runs only when "
                 "the negotiation is still mid-stream (the strategy "
                 "needs the buyer's ceiling).",
        ),
        duration_hours: Optional[float] = typer.Option(
            None, "--duration-hours", "-t",
            help="Lease duration the buyer wants (hours, fractional ok). "
                 "Required for fresh runs — sent to the seller's "
                 "/negotiate/new and validated against the listing's "
                 "max_duration_seconds. Resumed runs read it from the run-log.",
        ),
        from_run: Optional[str] = typer.Option(
            None, "--from",
            help="Resume a partial buy run-id end-to-end. Continues "
                 "negotiation if it stopped mid-stream, then drives "
                 "escrow.create + /settle + poll. The same run-log is "
                 "appended to so `market logs show <id>` captures the "
                 "full lifecycle.",
        ),
        registry_url: Optional[str] = typer.Option(
            None, "--registry-url",
            help="Registry base URL (default: registry.url from config.toml).",
        ),
        token_contract: Optional[str] = typer.Option(
            None, "--token-contract",
            help="ERC-20 token contract address used for payment. "
                 "Default: resolve 'MOCK' via the token registry.",
        ),
        token_decimals: int = typer.Option(
            18, "--token-decimals",
            help="ERC-20 token decimals (default 18).",
        ),
        chain_name: Optional[str] = typer.Option(
            None, "--chain-name",
            help="Chain name for alkahest address resolution "
                 "(default: chain.name from config.toml).",
        ),
        alkahest_addr_config: Optional[str] = typer.Option(
            None, "--alkahest-addr-config",
            help="Path to alkahest address config JSON "
                 "(default: chain.alkahest_address_config_path).",
        ),
        expiration_seconds: int = typer.Option(
            3600, "--expiration",
            help="Escrow deadline (seconds from now) for the "
                 "reclaim_expired escape hatch. Default 1h.",
        ),
        max_matches: int = typer.Option(
            5, "--max-matches",
            help="How many matching seller orders to try before giving up.",
        ),
        max_rounds: int = typer.Option(
            10, "--max-rounds",
            help="Per-negotiation round cap.",
        ),
        poll_interval: float = typer.Option(
            5.0, "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            600.0, "--settlement-timeout",
            help="Max seconds to wait for provisioning before giving up.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet (default: wallet.address from config.toml).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        ssh_public_key: Optional[str] = typer.Option(
            None, "--ssh-public-key",
            help="SSH public key for provisioning (default: wallet.ssh_public_key).",
        ),
        rpc_url: Optional[str] = typer.Option(
            None, "--rpc-url",
            help="Chain RPC URL (default: chain.rpc_url).",
        ),
    ) -> None:
        """Run a buy end-to-end as a pure HTTP/web3 client.

        No buyer agent is started or consulted; every step is either a
        signed HTTP call to a seller, a registry query, or a direct
        on-chain call.

        When ``--from <run_id>`` is supplied, picks up wherever the
        prior run left off: finishes the negotiation if it stopped
        mid-stream, then drives stages 3-5 (escrow → submit → poll).
        """
        console = Console()

        if from_run:
            _run_resume_from(
                from_run=from_run,
                max_price=max_price,
                buyer_address=buyer_address,
                buyer_private_key=buyer_private_key,
                ssh_public_key=ssh_public_key,
                token_contract=token_contract,
                token_decimals=token_decimals,
                rpc_url=rpc_url,
                chain_name=chain_name,
                alkahest_addr_config=alkahest_addr_config,
                expiration_seconds=expiration_seconds,
                max_rounds=max_rounds,
                poll_interval=poll_interval,
                settlement_timeout=settlement_timeout,
                console=console,
            )
            return

        if initial_price is None or max_price is None:
            typer.secho(
                "Fresh `market buy` runs require --initial-price and "
                "--max-price. To resume a prior run pass --from <run-id>.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if duration_hours is None or duration_hours <= 0:
            typer.secho(
                "Fresh `market buy` runs require --duration-hours "
                "(the buyer's lease ask).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        duration_seconds = int(round(duration_hours * 3600))

        # Resolution: CLI flag > config.toml > default.
        addr = resolve_config_value(
            override=buyer_address, toml_path="wallet.address",
        )
        pk = resolve_config_value(
            override=buyer_private_key, toml_path="wallet.private_key",
        )
        ssh = resolve_config_value(
            override=ssh_public_key, toml_path="wallet.ssh_public_key",
        )
        reg = resolve_config_value(
            override=registry_url, toml_path="registry.url",
        )
        rpc = resolve_config_value(
            override=rpc_url, toml_path="chain.rpc_url",
        )
        chain = resolve_config_value(
            override=chain_name, toml_path="chain.name",
            default="ethereum_sepolia",
        )
        addr_cfg = resolve_config_value(
            override=alkahest_addr_config,
            toml_path="chain.alkahest_address_config_path",
        )

        missing = [n for n, v in (
            ("buyer_address", addr), ("buyer_priv_key", pk),
            ("ssh_public_key", ssh), ("registry_url", reg),
            ("rpc_url", rpc),
        ) if not v]
        if missing:
            typer.secho(
                f"Missing required config: {', '.join(missing)}. "
                "Pass --flags or set corresponding env vars.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        # Resolve token contract if not explicitly given. Deferred import
        # so users without the token registry file can still pass --token-contract.
        tc = token_contract
        if not tc:
            try:
                from service.clients.token import TOKEN_REGISTRY
                meta = TOKEN_REGISTRY.require("MOCK")
                tc = meta.contract_address
                token_decimals = meta.decimals
            except Exception as exc:
                typer.secho(
                    f"Could not resolve default token 'MOCK' — pass "
                    f"--token-contract and --token-decimals. ({exc})",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)

        # Build the escrow hook.
        from ..escrow_client import make_create_escrow_fn
        create_escrow = make_create_escrow_fn(
            private_key=pk,
            rpc_url=rpc,
            chain_name=chain,
            addr_config_path=addr_cfg or None,
            token_contract_address=tc,
            token_decimals=token_decimals,
            expiration_seconds=expiration_seconds,
        )

        config = BuyConfig(
            registry_url=reg,
            buyer_address=addr,
            buyer_private_key=pk,
            ssh_public_key=ssh,
        )
        constraints = BuyConstraints(
            max_price=max_price,
            initial_price=initial_price,
            duration_seconds=duration_seconds,
        )

        run_log = RunLog.start(
            command="market buy",
            buyer_address=addr,
            registry_url=reg,
            initial_price=initial_price,
            max_price=max_price,
            duration_seconds=duration_seconds,
            max_matches=max_matches,
            max_rounds=max_rounds,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        header.add_row("Registry", reg)
        header.add_row("Buyer wallet", addr)
        header.add_row("Opening bid / ceiling", f"{initial_price} / {max_price}")
        header.add_row("Max matches", str(max_matches))
        console.print(Panel(header, title="market buy-sync", border_style="cyan"))

        def _observe(stage: str, body: dict) -> None:
            # Append a structured event to the run log so post-mortem
            # `market logs` and (eventually) `market buy --resume` have
            # something to read. Negotiation-scoped events carry
            # listing_id (and negotiation_id once round 0 returns) so
            # consumers can group per-negotiation.
            run_log.event(stage, **body)

            # Plus a one-line console summary for the human.
            if stage == "discover":
                console.print(f"[dim]discover[/dim]  {body.get('match_count', 0)} match(es)")
            elif stage == "negotiation_started":
                console.print(f"[dim]negotiate →[/dim] {body.get('seller_url')} ({body.get('listing_id')})")
            elif stage == "negotiation_round":
                rd = body.get("round", "?")
                their = body.get("their_reply") or {}
                console.print(
                    f"[dim]  round {rd}[/dim]  → {their.get('action', '-')}"
                    f" @ {their.get('price', '-')}"
                )
            elif stage == "negotiation_completed":
                color = "green" if body.get("status") == "agreed" else "yellow"
                console.print(
                    f"[{color}]negotiate ←[/{color}] {body.get('status')} "
                    f"@ {body.get('agreed_price', '-')}  "
                    f"({body.get('rounds', '-')} rounds)"
                )
            elif stage == "negotiation_failed":
                console.print(f"[red]negotiate ✗[/red]  {body.get('error')}")
            elif stage == "escrow_created":
                console.print(f"[green]escrow[/green]    {body.get('escrow_uid')}")
            elif stage == "settlement_submitted":
                console.print(f"[dim]settle →[/dim]  {body.get('escrow_uid')}")
            elif stage == "settlement_poll":
                st = (body.get("body") or {}).get("status")
                console.print(f"[dim]poll #{body.get('attempt')}[/dim]  status={st}")

        try:
            result = run_buy(
                config=config,
                constraints=constraints,
                create_escrow=create_escrow,
                max_matches_to_try=max_matches,
                max_negotiation_rounds=max_rounds,
                settlement_poll_interval=poll_interval,
                settlement_total_timeout=settlement_timeout,
                on_event=_observe,
            )
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Buy failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        run_log.end(
            result.status,
            seller_url=result.seller_url,
            negotiation_id=result.negotiation_id,
            agreed_price=result.agreed_price,
            escrow_uid=result.escrow_uid,
            attestation_uid=result.attestation_uid,
            reason=result.reason,
        )

        # Render the final outcome.
        tbl = Table.grid(padding=(0, 2))
        tbl.add_column(style="bold")
        tbl.add_column()
        tbl.add_row("Status", result.status)
        for label, val in (
            ("Seller", result.seller_url),
            ("Negotiation", result.negotiation_id),
            ("Agreed price", result.agreed_price),
            ("Escrow UID", result.escrow_uid),
            ("Attestation", result.attestation_uid),
            ("Reason", result.reason),
        ):
            if val:
                tbl.add_row(label, str(val))
        if result.connection_details:
            tbl.add_row("Connection", result.connection_details)
        if result.tenant_credentials:
            tbl.add_row("Tenant creds", json.dumps(result.tenant_credentials))

        border = {
            "ready": "green",
            "failed": "red",
            "timeout": "red",
            "exited": "yellow",
            "no_matches": "yellow",
        }.get(result.status, "white")
        console.print(Panel(tbl, title="Buy complete", border_style=border))

        if result.status != "ready":
            raise typer.Exit(4)
