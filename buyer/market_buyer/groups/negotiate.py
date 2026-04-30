"""`market negotiate` — buyer-as-client sync negotiation, one deal.

Thin wrapper around buyer_client.negotiate_with_seller(). Demonstrates
the pattern end-to-end: the CLI makes no agent assumptions, runs
entirely as an HTTP client talking to the seller.

Intended as a building block for the full market-buy rewrite; for now,
exists to exercise /negotiate/new + /negotiate/{id} directly.
"""

from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..common import resolve_config_value
from ..buyer_client import ResumeState, negotiate_with_seller
from ..run_log import RunLog
from ._deal import load_negotiation_resume_point


def register(app: typer.Typer) -> None:
    """Register the top-level `market negotiate` command."""

    @app.command("negotiate")
    def negotiate(
        seller_url: Optional[str] = typer.Option(
            None, "--seller", "-s",
            help="Seller agent base URL. Required for fresh runs; "
                 "resumed runs (--from) read it from the run-log.",
        ),
        listing_id: Optional[str] = typer.Option(
            None, "--listing-id",
            help="The seller's listing_id. Required for fresh runs; "
                 "resumed runs (--from) read it from the run-log.",
        ),
        initial_price: Optional[int] = typer.Option(
            None, "--initial-price",
            help="Opening bid in raw token units. Required for fresh runs.",
        ),
        max_price: Optional[int] = typer.Option(
            None, "--max-price",
            help="Ceiling — accept any seller counter at or under this. "
                 "Required for fresh runs; resumed runs reuse the original.",
        ),
        max_rounds: int = typer.Option(
            10, "--max-rounds",
            help="Walk away after this many buyer-initiated counters.",
        ),
        from_run: Optional[str] = typer.Option(
            None, "--from",
            help="Resume the round loop of a prior `market negotiate` run "
                 "(by run-id). Skips /negotiate/new; replays the seller's "
                 "last counter into the strategy and continues. Useful "
                 "when the buyer crashed mid-round but the seller's "
                 "thread state is still live.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet address (default: wallet.address).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        duration_hours: Optional[float] = typer.Option(
            None, "--duration-hours", "-t",
            help="Lease duration the buyer wants (hours, fractional ok). "
                 "Required for fresh runs — sent on /negotiate/new and "
                 "validated server-side against the listing's max_duration_seconds. "
                 "Resumed runs read it from the run-log.",
        ),
        token_contract: Optional[str] = typer.Option(
            None, "--token-contract",
            help="Payment token contract address. Logged for downstream "
                 "`market settle` / `escrow create`.",
        ),
        token_decimals: Optional[int] = typer.Option(
            None, "--token-decimals",
            help="Payment token decimals. Logged for downstream "
                 "`market settle` / `escrow create`.",
        ),
    ) -> None:
        """Drive a synchronous negotiation with one seller, round-by-round.

        Each round is a signed HTTP POST to the seller. The seller's
        policy decides counter/accept/exit and returns the decision
        inline. The buyer's policy (simple ceiling + midpoint counter)
        runs locally in this process.
        """
        console = Console()

        # Resolution: CLI flag > config.toml.
        addr = resolve_config_value(
            override=buyer_address, toml_path="wallet.address",
        )
        pk = resolve_config_value(
            override=buyer_private_key, toml_path="wallet.private_key",
        )
        if not addr or not pk:
            typer.secho(
                "Missing buyer wallet config. Pass --buyer-address + --buyer-priv-key "
                "or set wallet.address + wallet.private_key in config.toml.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        resume_state = None
        if from_run:
            resume_point = load_negotiation_resume_point(from_run)
            seller_url = seller_url or resume_point.seller_url
            listing_id = listing_id or resume_point.listing_id
            if max_price is None:
                typer.secho(
                    "--max-price is required when resuming (the strategy "
                    "needs the buyer's ceiling).",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            resume_state = ResumeState(
                negotiation_id=resume_point.negotiation_id,
                transcript=resume_point.transcript,
                last_seller_price=resume_point.last_seller_price,
                rounds_completed=resume_point.rounds_completed,
            )

        if not seller_url or not listing_id:
            typer.secho(
                "Missing required negotiation inputs. For a fresh run pass "
                "--seller and --listing-id; for a resume pass --from <run-id>.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        if resume_state is None and (initial_price is None or max_price is None):
            typer.secho(
                "Fresh runs require --initial-price and --max-price.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if resume_state is None and (duration_hours is None or duration_hours <= 0):
            typer.secho(
                "Fresh runs require --duration-hours (the buyer's lease ask).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        duration_seconds = (
            int(round(duration_hours * 3600)) if duration_hours is not None else None
        )

        # Best-effort: fetch the seller's on-chain wallet from the
        # /.well-known/agent-wallet.json endpoint and log it. Failure
        # is non-fatal — the negotiation itself doesn't need this; we
        # log it only so a follow-up `settle --run <id>` can avoid
        # re-fetching. A later `_resolve_seller_wallet` call from the
        # settle path will fall back to a fresh HTTP fetch if absent.
        seller_wallet: Optional[str] = None
        try:
            from ..buy_orchestrator import _resolve_seller_wallet
            seller_wallet = _resolve_seller_wallet(seller_url)
        except Exception as exc:
            typer.secho(
                f"(warn) could not resolve seller wallet from "
                f"{seller_url}/.well-known/agent-wallet.json: {exc}. "
                f"Negotiating anyway; settle will retry the lookup.",
                fg=typer.colors.YELLOW,
            )

        run_log = RunLog.start(
            command="market negotiate",
            seller_url=seller_url,
            listing_id=listing_id,
            buyer_address=addr,
            initial_price=initial_price,
            max_price=max_price,
            max_rounds=max_rounds,
            seller_wallet_address=seller_wallet,
            duration_seconds=duration_seconds,
            token_contract=token_contract,
            token_decimals=token_decimals,
            resumed_from=from_run,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        if from_run:
            header.add_row("Resumed from", from_run)
        header.add_row("Seller", seller_url)
        header.add_row("Listing", listing_id)
        if initial_price is not None:
            header.add_row("Opening bid", str(initial_price))
        header.add_row("Ceiling", str(max_price))
        header.add_row("Max rounds", str(max_rounds))
        console.print(Panel(header, title="market negotiate", border_style="cyan"))

        round_table = Table(title="Rounds", show_lines=False)
        round_table.add_column("#")
        round_table.add_column("Our action")
        round_table.add_column("Our price")
        round_table.add_column("Seller action")
        round_table.add_column("Seller price")

        def _observe(round_idx: int, our_msg: dict, reply: dict) -> None:
            run_log.event(
                "negotiation_round",
                round=round_idx,
                our_message=our_msg,
                their_reply=reply,
            )
            round_table.add_row(
                str(round_idx),
                str(our_msg.get("action", "propose")),
                str(our_msg.get("price") or our_msg.get("initial_price") or "-"),
                str(reply.get("action", "-")),
                str(reply.get("price", "-")),
            )

        try:
            outcome = negotiate_with_seller(
                seller_url=seller_url,
                buyer_address=addr,
                buyer_private_key=pk,
                listing_id=listing_id,
                initial_price=initial_price or 0,
                max_price=max_price,
                duration_seconds=duration_seconds,
                max_rounds=max_rounds,
                on_round=_observe,
                resume=resume_state,
            )
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Negotiation failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        run_log.end(
            outcome.status,
            negotiation_id=outcome.negotiation_id,
            agreed_price=outcome.agreed_price,
            rounds=outcome.rounds,
            reason=outcome.reason,
        )

        console.print(round_table)

        result_table = Table.grid(padding=(0, 2))
        result_table.add_column(style="bold")
        result_table.add_column()
        result_table.add_row("Status", outcome.status)
        if outcome.negotiation_id:
            result_table.add_row("Negotiation", outcome.negotiation_id)
        if outcome.agreed_price is not None:
            result_table.add_row("Agreed price", str(outcome.agreed_price))
        if outcome.reason:
            result_table.add_row("Reason", outcome.reason)
        result_table.add_row("Rounds", str(outcome.rounds))

        border = "green" if outcome.status == "agreed" else "yellow"
        console.print(Panel(result_table, title="Outcome", border_style=border))

        if outcome.status != "agreed":
            raise typer.Exit(4)
