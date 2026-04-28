"""`market negotiate` — buyer-as-client sync negotiation, one deal.

Thin wrapper around buyer_client.negotiate_with_seller(). Demonstrates
the pattern end-to-end: the CLI makes no agent assumptions, runs
entirely as an HTTP client talking to the seller.

Intended as a building block for the full market-buy rewrite; for now,
exists to exercise /negotiate/new + /negotiate/{id} directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..common import read_env_value, resolve_config_value
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
        env: Optional[str] = typer.Option(
            None, "--env", "-e",
            help="Env file for AGENT_WALLET_ADDRESS + AGENT_PRIV_KEY.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet address (default: from env).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: from env).",
        ),
    ) -> None:
        """Drive a synchronous negotiation with one seller, round-by-round.

        Each round is a signed HTTP POST to the seller. The seller's
        policy decides counter/accept/exit and returns the decision
        inline. The buyer's policy (simple ceiling + midpoint counter)
        runs locally in this process.
        """
        console = Console()
        env_path = Path(env) if env else None

        # Same hierarchy as `market buy` — see common.resolve_config_value.
        addr = resolve_config_value(
            "AGENT_WALLET_ADDRESS", override=buyer_address,
            env_file=env_path, toml_path="wallet.address",
        )
        pk = resolve_config_value(
            "AGENT_PRIV_KEY", override=buyer_private_key,
            env_file=env_path, toml_path="wallet.private_key",
        )
        if not addr or not pk:
            typer.secho(
                "Missing buyer wallet config. Pass --buyer-address + --buyer-priv-key "
                "or set AGENT_WALLET_ADDRESS + AGENT_PRIV_KEY.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        run_log = RunLog.start(
            command="market negotiate",
            seller_url=seller_url,
            seller_order_id=seller_order_id,
            buyer_address=addr,
            initial_price=initial_price,
            max_price=max_price,
            max_rounds=max_rounds,
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
