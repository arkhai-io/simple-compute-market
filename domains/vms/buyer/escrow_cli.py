"""`market escrow` — buyer-side escrow lifecycle commands.

Three verbs:
  create   — stage 3 only: alkahest approve + escrow.create on-chain
  reclaim  — post-expiration reclaim_expired via the matching escrow codec
  show     — read-only EVM inspection via the matching escrow codec

Refunds (post-claim manual return of tokens by the seller) live under
`market-storefront escrow refund`. The full create+submit+poll
composite lives at `market settle`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from market_buyer.common import resolve_config_value


escrow_app = typer.Typer(no_args_is_help=True)


def _resolve_escrow_uid_from_run(run_id: str) -> Optional[str]:
    """Read a buyer run-log JSONL and return the most recent
    escrow_uid logged by the buy_orchestrator."""
    from market_buyer.run_log import read_run

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


def _resolve_escrow_context_from_run(
    run_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(escrow_uid, chain_name, escrow_address)`` from a run-log."""
    if not run_id:
        return None, None, None
    try:
        from market_buyer.groups._deal import load_deal_context

        deal = load_deal_context(run_id)
    except Exception:
        return _resolve_escrow_uid_from_run(run_id), None, None

    chain_name = None
    escrow_address = None
    if isinstance(deal.accepted_escrow_terms, list) and deal.accepted_escrow_terms:
        terms = next(
            (
                item for item in deal.accepted_escrow_terms
                if isinstance(item, dict) and item.get("maker") == "buyer"
            ),
            deal.accepted_escrow_terms[0],
        )
        if isinstance(terms, dict):
            raw_chain = terms.get("chain_name")
            raw_address = terms.get("escrow_contract")
            if isinstance(raw_chain, str) and raw_chain:
                chain_name = raw_chain
            if isinstance(raw_address, str) and raw_address:
                escrow_address = raw_address
    if isinstance(deal.accepted_escrow_proposal, dict):
        raw_chain = deal.accepted_escrow_proposal.get("chain_name")
        raw_address = deal.accepted_escrow_proposal.get("escrow_address")
        if isinstance(raw_chain, str) and raw_chain:
            chain_name = raw_chain
        if isinstance(raw_address, str) and raw_address:
            escrow_address = raw_address
    return deal.escrow_uid, chain_name, escrow_address


def _format_obligation_value(value: object) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, list):
        return "[" + ", ".join(_format_obligation_value(v) for v in value) + "]"
    return str(value)


def _get_obligation_field(obligation: object, field: str) -> object | None:
    if isinstance(obligation, dict):
        return obligation.get(field)
    return getattr(obligation, field, None)


def _render_obligation_data(body: Table, obligation: object) -> None:
    fields = [
        "arbiter",
        "demand",
        "token",
        "tokenId",
        "amount",
        "nativeAmount",
        "erc20Tokens",
        "erc20Amounts",
        "erc721Tokens",
        "erc721TokenIds",
        "erc1155Tokens",
        "erc1155TokenIds",
        "erc1155Amounts",
        "attestation",
        "attestationUid",
    ]
    rendered = False
    for field in fields:
        value = _get_obligation_field(obligation, field)
        if value is None:
            continue
        body.add_row(field, _format_obligation_value(value))
        rendered = True
    if not rendered:
        body.add_row("Data", str(obligation))


async def _do_reclaim(
    *,
    private_key: str,
    rpc_url: str,
    chain_name: str,
    addr_config_path: Optional[str],
    escrow_uid: str,
    escrow_address: str | None = None,
) -> tuple[str, object]:
    """Run the on-chain reclaim_expired call and return the receipt."""
    from alkahest_py import AlkahestClient
    from service.clients.alkahest import (
        get_alkahest_network,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
        reclaim_expired_escrow_with_codec,
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
    codec, receipt = await reclaim_expired_escrow_with_codec(
        client,
        escrow_uid,
        chain_name=chain_name,
        config_path=addr_config_path,
        escrow_address=escrow_address,
    )
    return codec.kind, receipt


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
        None, "--chain",
        help="Which [chains.<name>] entry to reclaim on. Required when "
             "more than one chain is configured.",
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
    run_chain_name = None
    escrow_address = None

    if not escrow_uid and not run_id:
        typer.secho(
            "Pass --escrow-uid <uid> or --run <run_id>.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    if run_id:
        run_uid, run_chain_name, escrow_address = _resolve_escrow_context_from_run(
            run_id,
        )
        if not escrow_uid:
            escrow_uid = run_uid
        if not escrow_uid:
            typer.secho(
                f"No escrow_uid found in run {run_id}. Pass --escrow-uid explicitly.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(3)

    pk = resolve_config_value(override=private_key, toml_path="wallet.private_key")
    if not pk:
        typer.secho(
            "Missing wallet.private_key (or --buyer-priv-key).",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    from market_buyer.common import select_chain_for_listing
    chain_cfg = select_chain_for_listing(
        listing=None, override=chain_name or run_chain_name, yes=False,
    )

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Escrow UID", escrow_uid)
    header.add_row("Chain", chain_cfg.name)
    if escrow_address:
        header.add_row("Escrow contract", escrow_address)
    header.add_row("RPC", chain_cfg.rpc_url)
    console.print(Panel(header, title="market escrow reclaim", border_style="cyan"))

    try:
        escrow_kind, receipt = asyncio.run(_do_reclaim(
            private_key=pk,
            rpc_url=chain_cfg.rpc_url,
            chain_name=chain_cfg.name,
            addr_config_path=chain_cfg.alkahest_address_config_path,
            escrow_uid=escrow_uid,
            escrow_address=escrow_address,
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
    result.add_row("Escrow kind", escrow_kind)
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
        help="Legacy ERC-20 token override for old run-logs without an "
             "accepted escrow proposal. Current run-logs create from the "
             "seller-accepted proposal.",
    ),
    token_decimals: Optional[int] = typer.Option(
        None, "--token-decimals",
        help="Legacy ERC-20 decimals override for old run-logs without an "
             "accepted escrow proposal.",
    ),
    chain_name_flag: Optional[str] = typer.Option(
        None, "--chain",
        help="Which [chains.<name>] entry to create the escrow on. Required "
             "when more than one chain is configured.",
    ),
    private_key: Optional[str] = typer.Option(
        None, "--buyer-priv-key",
        help="Override buyer private key (default: wallet.private_key).",
    ),
    buyer_address: Optional[str] = typer.Option(
        None, "--buyer-address",
        help="Override buyer wallet address (default: derived from wallet.private_key).",
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

    from market_buyer.groups._deal import load_deal_context, open_run_log, resolve_chain_settings
    from market_buyer.buy_orchestrator import AgreedTerms
    from domains.vms.settlement import (
        make_buyer_payment_escrow_terms_fn,
        make_create_escrow_fn,
    )
    from market_buyer.common import chain_by_name, select_chain_for_listing

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
    proposal_chain = None
    if isinstance(deal.accepted_escrow_terms, list) and deal.accepted_escrow_terms:
        first_terms = deal.accepted_escrow_terms[0]
        if isinstance(first_terms, dict):
            raw_chain = first_terms.get("chain_name")
            if isinstance(raw_chain, str) and raw_chain:
                proposal_chain = raw_chain
    if isinstance(deal.accepted_escrow_proposal, dict):
        raw_chain = deal.accepted_escrow_proposal.get("chain_name")
        if isinstance(raw_chain, str) and raw_chain:
            proposal_chain = raw_chain
    if deal.accepted_escrow_terms is not None or deal.accepted_escrow_proposal is not None:
        if not (chain_name_flag or proposal_chain):
            typer.secho(
                "Accepted escrow proposal in run-log has no chain_name; pass --chain.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        chain_cfg = chain_by_name(chain_name_flag or proposal_chain)
        from market_buyer.common import resolve_buyer_wallet
        _, resolved_private_key = resolve_buyer_wallet(
            override_addr=buyer_address,
            override_pk=private_key,
        )
        if not resolved_private_key:
            typer.secho("Missing required config: wallet.private_key", err=True, fg=typer.colors.RED)
            raise typer.Exit(2)
        chain = SimpleNamespace(
            buyer_private_key=resolved_private_key,
            rpc_url=chain_cfg.rpc_url,
            chain_name=chain_cfg.name,
            alkahest_addr_config=chain_cfg.alkahest_address_config_path,
            token_contract=effective_token or "",
            token_decimals=effective_token_decimals,
        )
    else:
        chain_cfg = select_chain_for_listing(
            listing=None, override=chain_name_flag, yes=False,
        )
        chain = resolve_chain_settings(
            buyer_address=buyer_address,
            buyer_private_key=private_key,
            ssh_public_key=None,
            chain=chain_cfg,
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
    if not seller_wallet and deal.accepted_escrow_proposal is None:
        error = (
            "Run-log does not contain a seller recipient. Re-run negotiation "
            "so the accepted escrow proposal is captured."
        )
        log.event("escrow_recipient_missing", error=error)
        typer.secho(error, err=True, fg=typer.colors.RED)
        raise typer.Exit(3)

    terms = AgreedTerms(
        seller_url=deal.seller_url,
        seller_wallet_address=seller_wallet or "",
        negotiation_id=deal.negotiation_id,
        listing_id=deal.listing_id,
        agreed_amount=deal.agreed_amount,
        duration_seconds=effective_duration_seconds,
    )
    log.event("escrow_create_start", terms=terms.__dict__)

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", run_id)
    header.add_row("Seller", deal.seller_url)
    if seller_wallet:
        header.add_row("Seller wallet", seller_wallet)
    header.add_row("Agreed price", str(deal.agreed_amount))
    header.add_row("Duration (seconds)", str(effective_duration_seconds))
    if chain.token_contract:
        header.add_row("Token", f"{chain.token_contract} (decimals={chain.token_decimals})")
    console.print(Panel(header, title="market escrow create", border_style="cyan"))

    if deal.accepted_escrow_terms is not None:
        from service.schemas import EscrowTerms

        escrow_terms_list = [
            EscrowTerms.model_validate(item)
            for item in deal.accepted_escrow_terms
        ]
    elif deal.accepted_escrow_proposal is not None:
        from service.schemas import EscrowProposal

        proposal = EscrowProposal(**deal.accepted_escrow_proposal)
        build_terms = make_buyer_payment_escrow_terms_fn(
            chain_name=chain.chain_name,
            addr_config_path=chain.alkahest_addr_config,
        )
        escrow_terms_list = build_terms(
            proposal,
            seller_wallet or "",
            float(deal.agreed_amount),
            int(effective_duration_seconds),
        )
    else:
        from service.schemas import EscrowProposal
        from service.clients.alkahest import get_erc20_escrow_obligation_nontierable
        import time as _time

        escrow_address = get_erc20_escrow_obligation_nontierable(
            chain.chain_name,
            config_path=chain.alkahest_addr_config or None,
        )
        proposal = EscrowProposal(
            chain_name=chain.chain_name,
            escrow_address=escrow_address,
            fields={"token": chain.token_contract},
            literal_fields={"token": chain.token_contract},
            expiration_unix=int(_time.time()) + expiration_seconds,
        )
        build_terms = make_buyer_payment_escrow_terms_fn(
            chain_name=chain.chain_name,
            addr_config_path=chain.alkahest_addr_config,
        )
        escrow_terms_list = build_terms(
            proposal,
            seller_wallet or "",
            float(deal.agreed_amount),
            int(effective_duration_seconds),
        )

    create_escrow = make_create_escrow_fn(
        private_key=chain.buyer_private_key,
        rpc_url=chain.rpc_url,
        chain_name=chain.chain_name,
        addr_config_path=chain.alkahest_addr_config,
    )
    try:
        escrow_uids = create_escrow(escrow_terms_list)
    except Exception as exc:
        log.event("escrow_create_failed", error=str(exc))
        typer.secho(
            f"escrow.create failed on-chain: {exc}",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(4) from exc
    if not escrow_uids:
        log.event("escrow_create_failed", error="no uid returned")
        typer.secho(
            "escrow.create returned no uid — buyer terms list was empty.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(4)
    escrow_uid = escrow_uids[0]

    log.event("escrow_created", escrow_uid=escrow_uid, chain_name=chain.chain_name)
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
    chain_name_flag: Optional[str] = typer.Option(
        None, "--chain",
        help="Which [chains.<name>] entry to read the escrow from. "
             "Required when more than one chain is configured.",
    ),
    escrow_address_flag: Optional[str] = typer.Option(
        None, "--escrow-address",
        help="Escrow obligation contract address. Optional when --run captured "
             "accepted escrow terms; otherwise the command tries registered codecs.",
    ),
) -> None:
    """Read an escrow attestation from chain state.

    Reads the escrow obligation via the matching escrow codec and displays
    the attestation envelope plus decoded obligation fields.
    """
    run_chain_name = None
    run_escrow_address = None
    if not escrow_uid and not run_id:
        typer.secho(
            "Pass --escrow-uid <uid> or --run <run_id>.",
            err=True, fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    if run_id:
        run_uid, run_chain_name, run_escrow_address = _resolve_escrow_context_from_run(
            run_id,
        )
        if not escrow_uid:
            escrow_uid = run_uid
        if not escrow_uid:
            typer.secho(
                f"No escrow_uid recorded in run {run_id}. "
                f"Pass --escrow-uid explicitly.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(3)

    from market_buyer.common import select_chain_for_listing
    chain_cfg = select_chain_for_listing(
        listing=None, override=chain_name_flag or run_chain_name, yes=False,
    )
    escrow_address = escrow_address_flag or run_escrow_address
    private_key = resolve_config_value(
        override=None, toml_path="wallet.private_key",
    )
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
        get_escrow_obligation_with_codec,
        prewarm_alkahest_address_config_cache,
        resolve_alkahest_address_config,
    )
    from alkahest_py import AlkahestClient

    try:
        prewarm_alkahest_address_config_cache(chain_cfg.alkahest_address_config_path)
        address_config = resolve_alkahest_address_config(
            get_alkahest_network(chain_cfg.name),
            config_path=chain_cfg.alkahest_address_config_path,
        )
    except Exception as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(2)

    client = AlkahestClient(
        private_key=private_key,
        rpc_url=chain_cfg.rpc_url,
        address_config=address_config,
    )

    try:
        codec, decoded = asyncio.run(
            get_escrow_obligation_with_codec(
                client,
                escrow_uid,
                chain_name=chain_cfg.name,
                config_path=chain_cfg.alkahest_address_config_path,
                escrow_address=escrow_address,
            )
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

    console = Console()
    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold")
    head.add_column()
    head.add_row("Escrow UID", att.uid)
    head.add_row("Escrow kind", codec.kind)
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
    _render_obligation_data(body, obligation)
    console.print(Panel(body, title="Escrow obligation data", border_style="cyan"))
