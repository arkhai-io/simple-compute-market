"""`market-storefront escrow` — seller-side escrow lifecycle commands.

Three verbs:
  claim  — collect an escrow on-chain after fulfillment.
  refund — direct ERC-20 transfer from the provider wallet, used when
           a deal can't settle through the normal release path
           (e.g. provisioning failed post-claim, dispute).
  show   — read-only EVM inspection (calls IEAS.getAttestation,
           decodes ERC-20 escrow obligation data).

Counterpart on the buyer side: `market escrow reclaim`, which pulls
tokens back when an escrow expired *unclaimed*. Reclaim is buyer-only;
claim/refund are seller-only; show is symmetric.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from storefront_client import StorefrontClientError, SyncStorefrontClient

from ..cli_common import resolve_storefront_url


escrow_app = typer.Typer(no_args_is_help=True)


def _submit_claim(
    agent_url: str,
    listing_id: str,
    fulfillment_uid: Optional[str],
    private_key: Optional[str],
) -> dict:
    """POST /listings/claim; returns the storefront's response as a dict."""
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.claim_listing(listing_id=listing_id, fulfillment_uid=fulfillment_uid)
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return {
        "status": resp.status,
        "listing_id": resp.listing_id,
        "fulfillment_uid": resp.fulfillment_uid,
        "claim_tx": resp.claim_tx,
        **resp.extra,
    }


def _submit_refund(
    agent_url: str,
    listing_id: str,
    buyer_address: str,
    amount: Optional[str],
    token: Optional[str],
    private_key: Optional[str],
) -> dict:
    """POST /listings/refund; returns the storefront's response as a dict."""
    with SyncStorefrontClient(agent_url, private_key=private_key) as client:
        try:
            resp = client.refund_listing(
                listing_id=listing_id,
                buyer_address=buyer_address,
                amount=amount,
                token=token,
            )
        except StorefrontClientError as exc:
            typer.secho(f"Storefront error: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return {
        "status": resp.status,
        "listing_id": resp.listing_id,
        "refund_tx": resp.refund_tx,
        **resp.extra,
    }


@escrow_app.command("claim")
def claim_cmd(
    listing_id: str = typer.Argument(..., help="Local listing ID on the provider storefront."),
    fulfillment_uid: Optional[str] = typer.Option(
        None, "--fulfillment-uid",
        help="Override the fulfillment_uid from local state. Use this if the seller's "
             "StringObligation attestation landed on-chain but the storefront DB is out of sync.",
    ),
    agent_url: Optional[str] = typer.Option(
        None, "--storefront-url", "-a",
        help="Provider storefront base URL (default: seller.base_url from config.toml).",
    ),
) -> None:
    """Collect an escrow on-chain after fulfillment.

    Once the fulfillment attestation is on-chain, this tells the storefront
    to run `escrow.collect(escrow_uid, fulfillment_uid)` and close the
    listing locally. Useful when the automatic post-fulfillment collection
    path failed or was never triggered (storefront restart, RPC outage, etc.).
    """
    console = Console()
    from ..utils.config import CONFIG
    base_url = resolve_storefront_url(agent_url, default_port=8001)
    private_key = CONFIG.agent_priv_key

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Storefront", base_url)
    header.add_row("Listing", listing_id)
    if fulfillment_uid:
        header.add_row("Fulfillment UID override", fulfillment_uid)
    console.print(Panel(header, title="market-storefront escrow claim", border_style="cyan"))

    try:
        resp = _submit_claim(base_url, listing_id, fulfillment_uid, private_key)
    except typer.Exit:
        raise

    status = str(resp.get("status", "?"))
    if status != "claimed":
        typer.secho(
            f"Claim did not succeed: status={status} detail={resp}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(7)

    result = Table.grid(padding=(0, 2))
    result.add_column(style="bold")
    result.add_column()
    result.add_row("Status", "claimed (listing closed)")
    result.add_row("Escrow UID", str(resp.get("escrow_uid", "-")))
    result.add_row("Fulfillment UID", str(resp.get("fulfillment_uid", "-")))
    result.add_row("Collect result", str(resp.get("collect_result", "-")))
    console.print(Panel(result, title="Claim complete", border_style="green"))


@escrow_app.command("refund")
def refund_cmd(
    listing_id: str = typer.Argument(..., help="Local listing ID on the provider storefront."),
    buyer_address: Optional[str] = typer.Option(
        None, "--buyer", "-b",
        help="0x-prefixed wallet address to receive the refund. "
             "Optional — the storefront resolves this from the listing's "
             "recorded buyer when omitted. Pass explicitly to override.",
    ),
    amount: Optional[str] = typer.Option(
        None, "--amount", "-n",
        help="Refund amount in base units (decimal-digit string; uint256-safe). "
             "Defaults to the listing's accepted_escrows[0].price_per_hour × "
             "agreed_duration_seconds // 3600.",
    ),
    token: Optional[str] = typer.Option(
        None, "--token",
        help="Override the refund token (0x contract address). Defaults to the "
             "token on the listing's accepted_escrows[0].",
    ),
    agent_url: Optional[str] = typer.Option(
        None, "--storefront-url", "-a",
        help="Provider storefront base URL (default: seller.base_url from config.toml).",
    ),
) -> None:
    """Refund a deal via direct ERC-20 transfer from the provider wallet.

    Bypasses the escrow contract: the provider pays the buyer out of
    their own balance. Use when provisioning failed post-claim, or the
    deal otherwise can't settle through the normal escrow release path.
    """
    console = Console()
    from ..utils.config import CONFIG
    base_url = resolve_storefront_url(agent_url, default_port=8001)
    private_key = CONFIG.agent_priv_key

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Storefront", base_url)
    header.add_row("Listing", listing_id)
    header.add_row("Buyer", buyer_address or "[dim]from listing record[/dim]")
    if amount:
        header.add_row("Amount", f"{amount} {token or '(listing default)'}")
    else:
        header.add_row("Amount", "[dim]default from listing[/dim]")
    console.print(Panel(header, title="market-storefront escrow refund", border_style="yellow"))

    try:
        resp = _submit_refund(
            base_url, listing_id, buyer_address, amount, token, private_key,
        )
    except typer.Exit:
        raise

    status = str(resp.get("status", "?"))
    if status != "refunded":
        typer.secho(
            f"Refund did not succeed: status={status} detail={resp}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(6)

    result = Table.grid(padding=(0, 2))
    result.add_column(style="bold")
    result.add_column()
    result.add_row("Status", "refunded")
    result.add_row("Tx hash", str(resp.get("tx_hash", "-")))
    result.add_row("From", str(resp.get("from_address", "-")))
    result.add_row("To", str(resp.get("to_address", "-")))
    from service.clients.token import render_token
    result.add_row("Token", render_token(resp.get("token")))
    result.add_row("Amount (raw)", str(resp.get("amount_raw", "-")))
    result.add_row("Block", str(resp.get("block_number", "-")))
    console.print(Panel(result, title="Refund complete", border_style="green"))


@escrow_app.command("show")
def show_cmd(
    escrow_uid: str = typer.Option(
        ..., "--escrow-uid", "-u",
        help="0x-prefixed escrow UID to inspect.",
    ),
) -> None:
    """Read an escrow attestation from chain state.

    Inputs come from CONFIG (chain.rpc_url, chain.name,
    chain.alkahest_address_config_path) — same TOML the seller uses
    at runtime. Symmetric with `market escrow show` on the buyer side.

    The EAS contract address is read from the alkahest address config
    (no longer overridable from the CLI — the alkahest SDK keeps every
    obligation/EAS/arbiter address in one config object).
    """
    import asyncio
    from ..utils.config import CONFIG
    from service.clients.alkahest import (
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )
    from alkahest_py import AlkahestClient

    rpc = CONFIG.chain_rpc_url
    if not rpc:
        typer.secho(
            "Missing chain.rpc_url in config.toml.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    if not CONFIG.agent_priv_key:
        typer.secho(
            "Missing seller.private_key in config.toml — alkahest_py "
            "requires a wallet key even for read-only inspection.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    try:
        prewarm_alkahest_address_config_cache(CONFIG.alkahest_address_config_path)
        address_config = resolve_alkahest_address_config(
            get_alkahest_network(CONFIG.chain_name),
            config_path=CONFIG.alkahest_address_config_path,
        )
    except Exception as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(2)

    client = AlkahestClient(
        private_key=CONFIG.agent_priv_key,
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
    border = "red" if is_revoked else "green"
    console.print(Panel(head, title="Escrow attestation", border_style=border))

    body = Table.grid(padding=(0, 2))
    body.add_column(style="bold")
    body.add_column()
    body.add_row("Arbiter", obligation.arbiter or "-")
    body.add_row("Token", obligation.token or "-")
    body.add_row(
        "Amount (raw)",
        str(int(obligation.amount)) if obligation.amount is not None else "-",
    )
    body.add_row("Demand", ("0x" + demand_bytes.hex()) if demand_bytes else "-")
    console.print(Panel(body, title="ERC-20 escrow obligation data", border_style="cyan"))
