"""`market buy-sync` — pure-client sequential buy.

No buyer agent, no event pipeline. Drives the deal end-to-end from the
CLI process:

    discover (registry) →
    negotiate each match (sync HTTP rounds) →
    pick agreed match →
    create escrow on-chain (alkahest-py in-process) →
    POST /settle/{uid} on seller →
    poll /settle/{uid}/status until ready/failed.

Expects the buyer's order to already exist in the registry — create it
with `market order create` first. The orchestrator itself is in
market.buy_orchestrator; this command just wires env → config → call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
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
from ..common import read_env_value


def register(app: typer.Typer) -> None:
    """Register the top-level `market buy-sync` command."""

    @app.command("buy-sync")
    def buy_sync(
        buyer_order_id: str = typer.Argument(
            ..., help="The buyer's order_id (must exist in the registry).",
        ),
        initial_price: int = typer.Option(
            ..., "--initial-price",
            help="Opening bid per negotiation (raw token units).",
        ),
        max_price: int = typer.Option(
            ..., "--max-price",
            help="Ceiling per negotiation (raw token units).",
        ),
        registry_url: Optional[str] = typer.Option(
            None, "--registry-url",
            help="Registry base URL. Default: INDEXER_URL env / env file.",
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
                 "(env: CHAIN_NAME).",
        ),
        alkahest_addr_config: Optional[str] = typer.Option(
            None, "--alkahest-addr-config",
            help="Path to alkahest address config JSON "
                 "(env: ALKAHEST_ADDRESS_CONFIG_PATH).",
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
        env: Optional[str] = typer.Option(
            None, "--env", "-e",
            help="Env file for AGENT_WALLET_ADDRESS, AGENT_PRIV_KEY, "
                 "CHAIN_RPC_URL, INDEXER_URL, CHAIN_NAME, etc.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet (default: AGENT_WALLET_ADDRESS).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: AGENT_PRIV_KEY).",
        ),
        ssh_public_key: Optional[str] = typer.Option(
            None, "--ssh-public-key",
            help="SSH public key for provisioning (default: SSH_PUBLIC_KEY env).",
        ),
        rpc_url: Optional[str] = typer.Option(
            None, "--rpc-url",
            help="Chain RPC URL (default: CHAIN_RPC_URL env).",
        ),
    ) -> None:
        """Run a buy end-to-end as a pure HTTP/web3 client.

        No buyer agent is started or consulted; every step is either a
        signed HTTP call to a seller, a registry query, or a direct
        on-chain call.
        """
        console = Console()
        env_path = Path(env) if env else None

        def _resolve(name: str, override: Optional[str] = None, default: str = "") -> str:
            if override:
                return override
            v = read_env_value(env_path, name) if env_path else None
            return v or os.getenv(name) or default

        addr = _resolve("AGENT_WALLET_ADDRESS", buyer_address)
        pk = _resolve("AGENT_PRIV_KEY", buyer_private_key)
        ssh = _resolve("SSH_PUBLIC_KEY", ssh_public_key)
        reg = registry_url or _resolve("INDEXER_URL")
        rpc = rpc_url or _resolve("CHAIN_RPC_URL")
        chain = chain_name or _resolve("CHAIN_NAME", default="ethereum_sepolia")
        addr_cfg = alkahest_addr_config or _resolve("ALKAHEST_ADDRESS_CONFIG_PATH")

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
            buyer_order_id=buyer_order_id,
            ssh_public_key=ssh,
        )
        constraints = BuyConstraints(
            max_price=max_price, initial_price=initial_price,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Registry", reg)
        header.add_row("Buyer order", buyer_order_id)
        header.add_row("Buyer wallet", addr)
        header.add_row("Opening bid / ceiling", f"{initial_price} / {max_price}")
        header.add_row("Max matches", str(max_matches))
        console.print(Panel(header, title="market buy-sync", border_style="cyan"))

        def _observe(stage: str, body: dict) -> None:
            # Keep the UI simple: just one line per event.
            if stage == "discover":
                console.print(f"[dim]discover[/dim]  {body.get('match_count', 0)} match(es)")
            elif stage == "negotiate_start":
                console.print(f"[dim]negotiate →[/dim] {body.get('seller_url')}")
            elif stage == "negotiate_end":
                oc = body.get("outcome", {})
                color = "green" if oc.get("status") == "agreed" else "yellow"
                price = oc.get("agreed_price", "-")
                rounds = oc.get("rounds", "-")
                console.print(
                    f"[{color}]negotiate ←[/{color}] {oc.get('status')} "
                    f"@ {price}  ({rounds} rounds)"
                )
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
            typer.secho(f"Buy failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

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
