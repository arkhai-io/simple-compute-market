"""`market escrow` — buyer-side escrow lifecycle commands.

Three verbs:
  create   — stage 3 only: alkahest approve + escrow.create on-chain
  reclaim  — post-expiration tokens-back via reclaim_expired
  show     — read-only EVM inspection (calls IEAS.getAttestation,
             decodes ERC-20 escrow obligation data)

Refunds (post-claim manual return of tokens by the seller) live under
`market-storefront escrow refund`. The full create+submit+poll
composite lives at `market settle`.
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


@escrow_app.command("create")
def create_cmd(
    run_id: str = typer.Option(
        ..., "--run", "-r",
        help="Buyer run-id from a prior `market negotiate` "
             "(see `market logs runs`).",
    ),
    duration_hours: Optional[float] = typer.Option(
        None, "--duration-hours", "-t",
        help="Override the lease duration the escrow funds (hours, fractional ok). "
             "Default: from the run-log if recorded.",
    ),
    expiration_seconds: int = typer.Option(
        3600, "--expiration",
        help="Escrow deadline (seconds from now) for the reclaim_expired "
             "escape hatch. Default 1h.",
    ),
    token_contract: Optional[str] = typer.Option(
        None, "--token-contract",
        help="ERC-20 contract address. Default: resolve 'MOCK' via the token registry.",
    ),
    token_decimals: Optional[int] = typer.Option(
        None, "--token-decimals",
        help="ERC-20 token decimals override. When omitted, reads "
             "the value recorded in the run-log; if that's also "
             "missing, falls back to a chain decimals() lookup.",
    ),
    chain_name_flag: Optional[str] = typer.Option(
        None, "--chain-name",
        help="Chain name for alkahest address resolution (default: chain.name).",
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc-url",
        help="Chain RPC URL (default: chain.rpc_url).",
    ),
    addr_config: Optional[str] = typer.Option(
        None, "--alkahest-addr-config",
        help="Path to alkahest address config JSON (default: chain.alkahest_address_config_path).",
    ),
    private_key: Optional[str] = typer.Option(
        None, "--buyer-priv-key",
        help="Override buyer private key (default: wallet.private_key).",
    ),
    buyer_address: Optional[str] = typer.Option(
        None, "--buyer-address",
        help="Override buyer wallet (default: wallet.address from config.toml).",
    ),
) -> None:
    """Create the on-chain escrow for a previously negotiated deal.

    Stage 3 of the deal pipeline only — does not POST `/settle/...`
    or poll. After this returns, run `market settle --run <run_id>`
    to submit settlement and poll to terminal. The settle command
    will detect the recorded `escrow_uid` and skip its own create
    branch.
    """
    console = Console()

    from ._deal import load_deal_context, open_run_log, resolve_chain_settings
    from ..buy_orchestrator import AgreedTerms, _resolve_seller_wallet
    from ..escrow_client import make_create_escrow_fn

    deal = load_deal_context(run_id)
    if deal.escrow_uid:
        typer.secho(
            f"Run-log already records escrow_uid={deal.escrow_uid}. "
            f"Nothing to do.",
            fg=typer.colors.YELLOW,
        )
        return

    effective_token = token_contract or deal.token_contract
    # Precedence: explicit override > run-log recording > chain lookup
    # (delegated to resolve_chain_settings when this is None).
    effective_token_decimals: Optional[int] = (
        int(token_decimals)
        if token_decimals is not None
        else (int(deal.token_decimals) if deal.token_decimals is not None else None)
    )
    chain = resolve_chain_settings(
        buyer_address=buyer_address,
        buyer_private_key=private_key,
        ssh_public_key=None,
        rpc_url=rpc_url,
        chain_name=chain_name_flag,
        alkahest_addr_config=addr_config,
        token_contract=effective_token,
        token_decimals=effective_token_decimals,
        require_ssh=False,
    )
    duration_seconds_override = (
        int(round(duration_hours * 3600)) if duration_hours is not None else None
    )
    effective_duration_seconds = (
        duration_seconds_override
        if duration_seconds_override is not None
        else deal.duration_seconds
    )

    log = open_run_log(run_id)

    seller_wallet = deal.seller_wallet_address
    if not seller_wallet:
        try:
            seller_wallet = _resolve_seller_wallet(deal.seller_url)
        except RuntimeError as exc:
            log.event("escrow_resolve_wallet_failed", error=str(exc))
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
        duration_seconds=effective_duration_seconds,
    )
    log.event("escrow_create_start", terms=terms.__dict__)

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", run_id)
    header.add_row("Seller", deal.seller_url)
    header.add_row("Seller wallet", seller_wallet)
    header.add_row("Agreed price", str(deal.agreed_price))
    header.add_row("Duration (seconds)", str(effective_duration_seconds))
    header.add_row("Token", f"{chain.token_contract} (decimals={chain.token_decimals})")
    console.print(Panel(header, title="market escrow create", border_style="cyan"))

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
        escrow_uid = create_escrow(terms)
    except Exception as exc:
        log.event("escrow_create_failed", error=str(exc))
        typer.secho(
            f"escrow.create failed on-chain: {exc}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(4) from exc

    log.event("escrow_created", escrow_uid=escrow_uid)
    result = Table.grid(padding=(0, 2))
    result.add_column(style="bold")
    result.add_column()
    result.add_row("Status", "created")
    result.add_row("Escrow UID", escrow_uid)
    result.add_row("Next step", f"market settle --run {run_id}")
    console.print(Panel(result, title="Escrow created", border_style="green"))


@escrow_app.command("show")
def show_cmd(
    escrow_uid: Optional[str] = typer.Option(
        None, "--escrow-uid", "-u",
        help="0x-prefixed escrow UID to inspect. If omitted, --run is required.",
    ),
    run_id: Optional[str] = typer.Option(
        None, "--run", "-r",
        help="Buyer run-id to look up the escrow_uid from "
             "(see `market logs runs`).",
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc-url",
        help="Chain RPC URL (default: chain.rpc_url).",
    ),
    chain_name_flag: Optional[str] = typer.Option(
        None, "--chain-name",
        help="Chain name for alkahest address resolution (default: chain.name).",
    ),
    addr_config: Optional[str] = typer.Option(
        None, "--alkahest-addr-config",
        help="Path to alkahest address config JSON "
             "(default: chain.alkahest_address_config_path).",
    ),
) -> None:
    """Read an escrow attestation from chain state.

    Reads the ERC-20 escrow obligation via alkahest's
    ``client.erc20.escrow.non_tierable.get_obligation(uid)`` and
    displays the attestation envelope (recipient, attester, times,
    revocation status) plus the decoded escrow fields (arbiter,
    demand, token, amount).
    """
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
                f"No escrow_uid recorded in run {run_id}. "
                f"Pass --escrow-uid explicitly.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(3)

    rpc = resolve_config_value(override=rpc_url, toml_path="chain.rpc_url")
    chain = resolve_config_value(
        override=chain_name_flag, toml_path="chain.name", default="ethereum_sepolia",
    )
    addr_cfg = resolve_config_value(
        override=addr_config, toml_path="chain.alkahest_address_config_path",
    )
    private_key = resolve_config_value(
        override=None, toml_path="wallet.private_key",
    )
    if not rpc:
        typer.secho(
            "Missing chain.rpc_url (or --rpc-url).",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    if not private_key:
        typer.secho(
            "Missing wallet.private_key in buyer.toml — alkahest_py "
            "requires a wallet key even for read-only inspection.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    import asyncio
    from service.clients.alkahest import (
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )
    from alkahest_py import AlkahestClient

    try:
        prewarm_alkahest_address_config_cache(addr_cfg or None)
        address_config = resolve_alkahest_address_config(
            get_alkahest_network(chain),
            config_path=addr_cfg or None,
        )
    except Exception as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(2)

    client = AlkahestClient(
        private_key=private_key,
        rpc_url=rpc,
        address_config=address_config,
    )

    try:
        decoded = asyncio.run(
            client.erc20.escrow.non_tierable.get_obligation(escrow_uid)
        )
    except Exception as exc:
        typer.secho(
            f"alkahest get_obligation failed: {exc}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(4) from exc

    att = decoded["attestation"]
    obligation = decoded["data"]
    is_revoked = bool(att.revocation_time)
    demand_bytes = bytes(obligation.demand) if obligation.demand is not None else None

    console = Console()
    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold")
    head.add_column()
    head.add_row("Escrow UID", att.uid)
    head.add_row("Schema", att.schema)
    head.add_row("Attester", att.attester)
    head.add_row("Recipient", att.recipient)
    head.add_row("Created at (unix)", str(att.time))
    head.add_row("Expiration (unix)", str(att.expiration_time) or "(no expiry)")
    head.add_row("Revoked at (unix)", str(att.revocation_time) or "(not revoked)")
    head.add_row("Ref UID", att.ref_uid)
    head.add_row("Revocable", "yes" if att.revocable else "no")
    title = "Escrow attestation"
    border = "red" if is_revoked else "green"
    console.print(Panel(head, title=title, border_style=border))

    body = Table.grid(padding=(0, 2))
    body.add_column(style="bold")
    body.add_column()
    body.add_row("Arbiter", obligation.arbiter or "-")
    body.add_row("Token", obligation.token or "-")
    body.add_row(
        "Amount (raw)",
        str(int(obligation.amount)) if obligation.amount is not None else "-",
    )
    body.add_row(
        "Demand",
        ("0x" + demand_bytes.hex()) if demand_bytes else "-",
    )
    console.print(Panel(body, title="ERC-20 escrow obligation data", border_style="cyan"))
