"""`market escrow` — buyer-side escrow lifecycle commands.

One verb today: `reclaim` — pull tokens back from an escrow that
expired without ever being claimed by a seller. The buyer's wallet is
the original payer, so the on-chain `reclaim_expired` call is signed
locally; no agent involvement.

Refunds (post-claim manual return of tokens) are seller-side and live
under `market-storefront escrow refund`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..common import resolve_config_value


escrow_app = typer.Typer(no_args_is_help=True)


def _resolve_escrow_uid_from_run(run_id: str) -> Optional[str]:
    """Read a buyer run-log JSONL and return the most recent
    escrow_uid logged by the buy_orchestrator."""
    from ..run_log import read_run

    events = read_run(run_id)
    if not events:
        return None
    for ev in reversed(events):
        uid = ev.get("escrow_uid")
        if isinstance(uid, str) and uid:
            return uid
        attempts = ev.get("attempts")
        if isinstance(attempts, list):
            for att in reversed(attempts):
                if isinstance(att, dict):
                    uid = att.get("escrow_uid")
                    if isinstance(uid, str) and uid:
                        return uid
    return None


async def _do_reclaim(
    *,
    private_key: str,
    rpc_url: str,
    chain_name: str,
    addr_config_path: Optional[str],
    escrow_uid: str,
) -> object:
    """Run the on-chain reclaim_expired call and return the receipt."""
    from alkahest_py import AlkahestClient
    from service.clients.alkahest import (
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )

    prewarm_alkahest_address_config_cache(addr_config_path)
    alkahest_network = get_alkahest_network(chain_name)
    address_config = resolve_alkahest_address_config(
        alkahest_network, config_path=addr_config_path,
    )
    client = AlkahestClient(
        private_key=private_key,
        rpc_url=rpc_url,
        address_config=address_config,
    )
    return await client.erc20.escrow.non_tierable.reclaim_expired(escrow_uid)


@escrow_app.command("reclaim")
def reclaim_cmd(
    escrow_uid: Optional[str] = typer.Option(
        None, "--escrow-uid", "-u",
        help="0x-prefixed escrow UID to reclaim. If omitted, --run is required.",
    ),
    run_id: Optional[str] = typer.Option(
        None, "--run", "-r",
        help="Buyer run id to look up the escrow_uid from "
             "(see `market logs runs`).",
    ),
    chain_name: Optional[str] = typer.Option(
        None, "--chain-name",
        help="Chain name for alkahest address resolution "
             "(default: chain.name from config.toml).",
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc-url",
        help="Chain RPC URL (default: chain.rpc_url).",
    ),
    addr_config: Optional[str] = typer.Option(
        None, "--alkahest-addr-config",
        help="Path to alkahest address config JSON "
             "(default: chain.alkahest_address_config_path).",
    ),
    private_key: Optional[str] = typer.Option(
        None, "--buyer-priv-key",
        help="Override buyer private key (default: wallet.private_key).",
    ),
) -> None:
    """Reclaim tokens from an expired, unclaimed escrow.

    On-chain `reclaim_expired` only succeeds after the escrow's
    `expiration` timestamp has passed *and* no fulfillment has been
    posted. The buyer's wallet must be the original payer.
    """
    console = Console()

    if not escrow_uid and not run_id:
        typer.secho(
            "Pass --escrow-uid <uid> or --run <run_id>.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    if not escrow_uid and run_id:
        escrow_uid = _resolve_escrow_uid_from_run(run_id)
        if not escrow_uid:
            typer.secho(
                f"No escrow_uid found in run {run_id}. Pass --escrow-uid explicitly.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(3)

    pk = resolve_config_value(override=private_key, toml_path="wallet.private_key")
    rpc = resolve_config_value(override=rpc_url, toml_path="chain.rpc_url")
    chain = resolve_config_value(
        override=chain_name, toml_path="chain.name", default="ethereum_sepolia",
    )
    addr = resolve_config_value(
        override=addr_config, toml_path="chain.alkahest_address_config_path",
    )

    missing = [k for k, v in {
        "wallet.private_key (or --buyer-priv-key)": pk,
        "chain.rpc_url (or --rpc-url)": rpc,
    }.items() if not v]
    if missing:
        typer.secho(
            f"Missing required config: {', '.join(missing)}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Escrow UID", escrow_uid)
    header.add_row("Chain", chain)
    header.add_row("RPC", rpc)
    console.print(Panel(header, title="market escrow reclaim", border_style="cyan"))

    try:
        receipt = asyncio.run(_do_reclaim(
            private_key=pk,
            rpc_url=rpc,
            chain_name=chain,
            addr_config_path=addr or None,
            escrow_uid=escrow_uid,
        ))
    except Exception as exc:
        typer.secho(
            f"reclaim_expired failed on-chain: {exc}",
            err=True, fg=typer.colors.RED,
        )
        typer.secho(
            "Most common cause: escrow expiration hasn't passed yet, "
            "or a fulfillment was already posted.",
            err=True, fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1) from exc

    result = Table.grid(padding=(0, 2))
    result.add_column(style="bold")
    result.add_column()
    result.add_row("Status", "reclaimed")
    result.add_row("Receipt", str(receipt))
    console.print(Panel(result, title="Reclaim complete", border_style="green"))
