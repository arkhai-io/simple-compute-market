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
from ..buyer_client import negotiate_with_seller
from ..run_log import RunLog


def register(app: typer.Typer) -> None:
    """Register the top-level `market negotiate` command."""

    @app.command("negotiate")
    def negotiate(
        seller_url: str = typer.Option(
            ..., "--seller", "-s",
            help="Seller agent base URL (e.g. http://seller:8001).",
        ),
        seller_order_id: str = typer.Option(
            ..., "--seller-order",
            help="The seller's order_id we're negotiating against.",
        ),
        initial_price: int = typer.Option(
            ..., "--initial-price",
            help="Opening bid in raw token units.",
        ),
        max_price: int = typer.Option(
            ..., "--max-price",
            help="Ceiling — accept any seller counter at or under this.",
        ),
        max_rounds: int = typer.Option(
            10, "--max-rounds",
            help="Walk away after this many buyer-initiated counters.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet address (default: wallet.address).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        duration_hours: Optional[int] = typer.Option(
            None, "--duration-hours", "-t",
            help="Lease duration the deal funds. Logged so a follow-on "
                 "`market settle --run <id>` can drive escrow.create "
                 "without re-passing it.",
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
            seller_order_id=seller_order_id,
            buyer_address=addr,
            initial_price=initial_price,
            max_price=max_price,
            max_rounds=max_rounds,
            seller_wallet_address=seller_wallet,
            duration_hours=duration_hours,
            token_contract=token_contract,
            token_decimals=token_decimals,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        header.add_row("Seller", seller_url)
        header.add_row("Seller order", seller_order_id)
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
                seller_order_id=seller_order_id,
                initial_price=initial_price,
                max_price=max_price,
                max_rounds=max_rounds,
                on_round=_observe,
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
