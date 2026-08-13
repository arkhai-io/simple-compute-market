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

from types import SimpleNamespace

import typer
from market_core.schemas import SettlementPlan
from market_identity import Identity
from market_settlement_runtime import derive_obligation_ref
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .buy_orchestrator import (
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
    AgreedTerms,
    submit_settlement_request,
    wait_for_settlement,
)
from .deal_helpers import (
    accepted_settlement_mechanism,
    load_deal_context,
    make_deal_publisher_trust_resolver,
    open_run_log,
    resolve_chain_settings,
)
from .escrow_client import looks_like_propagation_lag
from .hosted_settlement import (
    start_hosted_settlement,
    wait_for_hosted_settlement,
)
from .run_log import read_run


def _chain_name_from_run_log(run_id: str, *, signer) -> str | None:
    """Look up the explicit EVM mechanism chain recorded for a run."""

    for ev in read_run(run_id, signer=signer):
        if ev.get("event") == "escrow_created":
            chain_name = ev.get("chain_name")
            if isinstance(chain_name, str) and chain_name:
                return chain_name
            terms = ev.get("terms") or {}
            chain_name = terms.get("chain_name")
            if isinstance(chain_name, str) and chain_name:
                return chain_name
        if ev.get("event") == "run_started":
            chain_name = ev.get("chain_name")
            if isinstance(chain_name, str) and chain_name:
                return chain_name
    return None


def _first_listing_chain(deal) -> str | None:
    """Fallback: pick the chain from the deal's listing accepted_escrows."""
    listing = getattr(deal, "listing", None)
    if isinstance(listing, dict):
        for entry in listing.get("accepted_escrows") or []:
            if isinstance(entry, dict):
                cn = entry.get("chain_name")
                if isinstance(cn, str) and cn:
                    return cn
    return None


def _accepted_proposal_chain(deal) -> str | None:
    terms = getattr(deal, "accepted_escrow_terms", None)
    if isinstance(terms, list) and terms:
        first = terms[0]
        if isinstance(first, dict):
            chain = first.get("chain_name")
            if isinstance(chain, str) and chain:
                return chain
    proposal = getattr(deal, "accepted_escrow_proposal", None)
    if isinstance(proposal, dict):
        chain = proposal.get("chain_name")
        if isinstance(chain, str) and chain:
            return chain
    return None


def _hosted_obligation(deal) -> dict | None:
    if deal.settlement_plan is None:
        return None
    plan = SettlementPlan.model_validate(deal.settlement_plan)
    hosted = [
        obligation
        for obligation in plan.obligations
        if obligation.mechanism == "fiat.stripe.v1"
    ]
    if not hosted:
        return None
    if len(plan.obligations) != 1 or len(hosted) != 1:
        raise ValueError("hosted recovery requires exactly one hosted obligation")
    return hosted[0].model_dump(mode="json")


def run_settle_from_log(
    *,
    run_id: str,
    escrow_uid: str | None,
    token_contract: str | None,
    token_decimals: int | None,
    duration_seconds: int | None,
    expiration_seconds: int,
    ssh_public_key: str | None,
    buyer_address: str | None,
    buyer_private_key: str | None,
    chain_name: str | None,
    poll_interval: float,
    settlement_timeout: float,
    console: Console | None = None,
) -> dict:
    """Drive stages 3-5 of a deal from a buyer run-log.

    Reusable by both ``market settle`` and ``market buy --from``.
    Reads the run-log for ``run_id``, creates the on-chain escrow if
    not already present, POSTs ``/settle/{escrow_uid}`` to the seller,
    and polls until terminal. Logs each stage transition back into
    the same run-log.

    Returns the final settle-status body. Raises ``typer.Exit`` on
    fatal errors (resolution failures, on-chain failures, polling
    timeout, non-``ready`` terminal status).
    """
    console = console or Console()
    from .common import (
        chain_by_name,
        resolve_buyer_signer,
        resolve_identity_config,
        resolve_identity_credential,
    )

    identity_config = resolve_identity_config()
    signer = resolve_buyer_signer(
        identity_config,
        resolve_identity_credential(),
    )
    deal = load_deal_context(run_id, signer=signer)
    resolve_seller_principals = make_deal_publisher_trust_resolver(run_id, deal, signer)
    log = open_run_log(run_id, signer=signer)
    log.event("settle_resumed", run_id=run_id)

    try:
        accepted_mechanism = accepted_settlement_mechanism(deal)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    hosted_obligation = _hosted_obligation(deal)
    if accepted_mechanism == "fiat.stripe.v1":
        if hosted_obligation is None:
            raise typer.BadParameter(
                "accepted hosted selection has no matching settlement obligation"
            )
        obligation_ref = derive_obligation_ref(
            deal.negotiation_id,
            0,
            hosted_obligation,
        )
        if (
            deal.settlement_operation_identities
            and deal.settlement_operation_identities[0] != obligation_ref
        ):
            raise typer.BadParameter(
                "accepted settlement operation identity conflicts with the run-log"
            )
        settlement_ref = escrow_uid or deal.settlement_ref
        if settlement_ref is None:
            started = start_hosted_settlement(
                seller_url=deal.seller_url,
                negotiation_id=deal.negotiation_id,
                obligation_ref=obligation_ref,
                payer_principal=Identity.model_validate(
                    hosted_obligation.get("payer_principal")
                ),
                claimant_principal=Identity.model_validate(
                    hosted_obligation.get("claimant_principal")
                ),
                principal=deal.buyer_principal,
                signer=signer,
                resolve_seller_principals=resolve_seller_principals,
            )
            settlement_ref = started.get("settlement_ref")
            if not isinstance(settlement_ref, str) or not settlement_ref:
                raise RuntimeError(
                    "storefront returned no opaque hosted settlement reference"
                )
            log.event(
                "settlement_started",
                settlement_ref=settlement_ref,
                settlement_operation_identity=obligation_ref,
                status=started.get("status"),
                action_kind=(started.get("action") or {}).get("kind"),
                action_expires_at_unix=(started.get("action") or {}).get(
                    "expires_at_unix"
                ),
            )

        def _open_action(action: dict) -> None:
            url = action.get("url")
            if isinstance(url, str) and url:
                import webbrowser

                console.print("[dim]opening hosted checkout action[/dim]")
                webbrowser.open(url)

        def _hosted_poll(attempt: int, body: dict) -> None:
            action = body.get("action") or {}
            log.event(
                "hosted_settlement_poll",
                attempt=attempt,
                settlement_ref=settlement_ref,
                status=body.get("status"),
                action_kind=action.get("kind"),
                action_expires_at_unix=action.get("expires_at_unix"),
            )

        final = wait_for_hosted_settlement(
            seller_url=deal.seller_url,
            settlement_ref=settlement_ref,
            principal=deal.buyer_principal,
            signer=signer,
            poll_interval=poll_interval,
            total_timeout=settlement_timeout,
            on_poll=_hosted_poll,
            on_action=_open_action,
            resolve_seller_principals=resolve_seller_principals,
        )
        status = str(final.get("status") or "unknown")
        log.event(
            "hosted_settlement_terminal",
            settlement_ref=settlement_ref,
            status=status,
        )
        log.end(status, settlement_ref=settlement_ref)
        if status not in {"ready", "collected"}:
            raise typer.Exit(7)
        return final

    if accepted_mechanism != "alkahest.v1":
        raise typer.BadParameter(
            f"accepted settlement mechanism {accepted_mechanism!r} is not installed; "
            "recovery will not fall back to another mechanism"
        )
    from .settlement_composition import resolve_alkahest_address_config_path

    alkahest_address_config_path = resolve_alkahest_address_config_path()

    effective_token = token_contract or deal.token_contract
    effective_token_decimals: int | None = (
        int(token_decimals)
        if token_decimals is not None
        else (int(deal.token_decimals) if deal.token_decimals is not None else None)
    )
    chain_cfg_name = (
        _accepted_proposal_chain(deal)
        or _chain_name_from_run_log(run_id, signer=signer)
        or chain_name
        or _first_listing_chain(deal)
    )
    if not chain_cfg_name:
        typer.secho(
            "Could not determine the selected EVM chain. Pass --chain.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain_cfg = chain_by_name(chain_cfg_name)
    if deal.accepted_escrow_proposal is not None:
        from .common import resolve_buyer_wallet, resolve_ssh_public_key

        resolved_buyer_address, resolved_buyer_private_key = resolve_buyer_wallet(
            override_addr=buyer_address,
            override_pk=buyer_private_key,
        )
        resolved_ssh_public_key = resolve_ssh_public_key(override=ssh_public_key)
        missing: list[str] = []
        if not resolved_buyer_address:
            missing.append("wallet.address")
        if not resolved_buyer_private_key:
            missing.append("wallet.private_key")
        if not resolved_ssh_public_key:
            missing.append("provisioning.ssh_public_key")
        if missing:
            typer.secho(
                "Missing required EVM config: " + ", ".join(missing),
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        chain = SimpleNamespace(
            buyer_address=resolved_buyer_address,
            buyer_private_key=resolved_buyer_private_key,
            ssh_public_key=resolved_ssh_public_key,
            rpc_url=chain_cfg.rpc_url,
            chain_name=chain_cfg.name,
            alkahest_addr_config=alkahest_address_config_path,
            token_contract=effective_token or "",
            token_decimals=effective_token_decimals,
        )
    else:
        chain = resolve_chain_settings(
            buyer_address=buyer_address,
            buyer_private_key=buyer_private_key,
            ssh_public_key=ssh_public_key,
            chain=chain_cfg,
            token_contract=effective_token,
            token_decimals=effective_token_decimals,
        )
        chain.alkahest_addr_config = alkahest_address_config_path

    resolved_uid = escrow_uid or deal.escrow_uid
    effective_duration = (
        duration_seconds if duration_seconds is not None else deal.duration_seconds
    )

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", run_id)
    header.add_row("Seller", deal.seller_url)
    header.add_row("Negotiation", deal.negotiation_id)
    header.add_row("Agreed price (per hour)", str(deal.agreed_amount))
    header.add_row("Duration (seconds)", str(effective_duration))
    if chain.token_contract:
        header.add_row(
            "Token", f"{chain.token_contract} (decimals={chain.token_decimals})"
        )
    if resolved_uid:
        header.add_row("Escrow UID", resolved_uid + " (skip create)")
    console.print(Panel(header, title="market settle", border_style="cyan"))

    # --- Stage 3: escrow.create (skip if uid already known) -------
    if not resolved_uid:
        seller_wallet = deal.seller_wallet_address
        if not seller_wallet and deal.accepted_escrow_proposal is None:
            error = (
                "Run-log does not contain a seller recipient. Re-run negotiation "
                "so the accepted escrow proposal is captured."
            )
            log.event("escrow_recipient_missing", error=error)
            log.end("error", error=error)
            typer.secho(error, err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        terms = AgreedTerms(
            seller_url=deal.seller_url,
            seller_wallet_address=seller_wallet or "",
            negotiation_id=deal.negotiation_id,
            listing_id=deal.listing_id,
            agreed_amount=deal.agreed_amount,
            duration_seconds=effective_duration,
        )
        log.event("escrow_create_start", terms=terms.__dict__)
        console.print("[dim]escrow.create[/dim]  approve + create on-chain…")

        import time as _time

        from market_alkahest.alkahest import (
            get_erc20_escrow_obligation_default,
        )
        from market_alkahest.schemas import EscrowProposal

        from .escrow_client import (
            make_buyer_payment_escrow_terms_fn,
            make_create_escrow_fn,
        )

        if deal.accepted_escrow_terms is not None:
            from market_alkahest.schemas import EscrowTerms

            escrow_terms_list = [
                EscrowTerms.model_validate(item) for item in deal.accepted_escrow_terms
            ]
        elif deal.accepted_escrow_proposal is not None:
            proposal = EscrowProposal(**deal.accepted_escrow_proposal)
        else:
            escrow_address = get_erc20_escrow_obligation_default(
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

        if deal.accepted_escrow_terms is None:
            build_terms = make_buyer_payment_escrow_terms_fn(
                chain_name=chain.chain_name,
                addr_config_path=chain.alkahest_addr_config,
            )
            escrow_terms_list = build_terms(
                proposal,
                seller_wallet,
                float(deal.agreed_amount),
                int(effective_duration),
            )

        create_escrow = make_create_escrow_fn(
            private_key=chain.buyer_private_key,
            rpc_url=chain.rpc_url,
            chain_name=chain.chain_name,
            addr_config_path=chain.alkahest_addr_config,
        )
        try:
            uids = create_escrow(escrow_terms_list)
        except Exception as exc:
            log.event("escrow_create_failed", error=str(exc))
            log.end("error", error=f"escrow_create: {exc}")
            typer.secho(
                f"escrow.create failed on-chain: {exc}",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(4) from exc
        if not uids:
            log.event("escrow_create_failed", error="no uid returned")
            log.end("error", error="escrow_create: no uid returned")
            typer.secho(
                "escrow.create returned no uid — buyer terms list was empty.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(4)
        resolved_uid = uids[0]
        log.event("escrow_created", escrow_uid=resolved_uid)
        console.print(f"[green]escrow created[/green]  {resolved_uid}")

    # --- Stage 4: submit settlement -------------------------------
    try:
        submit_body = submit_settlement_request(
            seller_url=deal.seller_url,
            escrow_uid=resolved_uid,
            payload={
                "negotiation_id": deal.negotiation_id,
                "ssh_public_key": chain.ssh_public_key,
                "buyer_evm_address": chain.buyer_address,
                "chain_name": chain.chain_name,
            },
            principal=deal.buyer_principal,
            signer=signer,
            max_attempts=6,
            retryable=looks_like_propagation_lag,
            resolve_seller_principals=resolve_seller_principals,
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
            principal=deal.buyer_principal,
            signer=signer,
            resolve_seller_principals=resolve_seller_principals,
            poll_interval=poll_interval,
            total_timeout=settlement_timeout,
            on_poll=_on_poll,
        )
    except TimeoutError as exc:
        log.event("settle_terminal", status="timeout", error=str(exc))
        log.end("timeout", escrow_uid=resolved_uid, error=str(exc))
        typer.secho(
            f"settlement polling timed out: {exc}", err=True, fg=typer.colors.YELLOW
        )
        raise typer.Exit(6) from exc

    log.event("settle_terminal", body=final)
    log.end(
        final.get("status") or "unknown",
        escrow_uid=resolved_uid,
        fulfillment_uid=final.get("fulfillment_uid"),
    )

    result = Table.grid(padding=(0, 2))
    result.add_column(style="bold")
    result.add_column()
    result.add_row("Status", str(final.get("status")))
    result.add_row("Escrow UID", resolved_uid)
    if final.get("fulfillment_uid"):
        result.add_row("Fulfillment UID", str(final["fulfillment_uid"]))
    if final.get("connection_details"):
        result.add_row("Connection", str(final["connection_details"]))
    if final.get("reason"):
        result.add_row("Reason", str(final["reason"]))
    border = "green" if final.get("status") == "ready" else "yellow"
    console.print(Panel(result, title="Settlement complete", border_style=border))

    if final.get("status") != "ready":
        raise typer.Exit(7)

    return final


def register(app: typer.Typer) -> None:
    """Register the top-level `market settle` command."""

    @app.command("settle")
    def settle(
        run_id: str = typer.Option(
            ...,
            "--from",
            "--run",
            "-r",
            help="Buyer run-id from a prior `market negotiate` to resume "
            "from (see `market logs runs`).",
        ),
        escrow_uid: str | None = typer.Option(
            None,
            "--escrow-uid",
            "-u",
            help="Skip escrow.create when the on-chain escrow already exists. "
            "If absent, the run-log is checked for an `escrow_created` event.",
        ),
        token_contract: str | None = typer.Option(
            None,
            "--token-contract",
            help="Legacy ERC-20 token override for old run-logs without an "
            "accepted escrow proposal. Current run-logs settle from the "
            "seller-accepted proposal.",
        ),
        token_decimals: int | None = typer.Option(
            None,
            "--token-decimals",
            help="Legacy ERC-20 decimals override for old run-logs without "
            "an accepted escrow proposal.",
        ),
        duration_hours: float | None = typer.Option(
            None,
            "--duration-hours",
            "-t",
            help="Override the lease duration the escrow funds (hours, fractional ok). "
            "Default: from the run-log if recorded.",
        ),
        expiration_seconds: int = typer.Option(
            3600,
            "--expiration",
            help="Escrow deadline (seconds from now) for the reclaim_expired escape hatch.",
        ),
        ssh_public_key: str | None = typer.Option(
            None,
            "--ssh-public-key",
            help="SSH public key for provisioning (default: wallet.ssh_public_key).",
        ),
        chain_name: str | None = typer.Option(
            None,
            "--chain",
            help="Override which configured [chains.<name>] entry to settle on. "
            "When omitted, reads chain_name from the accepted proposal "
            "or escrow_created event.",
        ),
        poll_interval: float = typer.Option(
            DEFAULT_SETTLEMENT_POLL_INTERVAL,
            "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            DEFAULT_SETTLEMENT_TIMEOUT,
            "--settlement-timeout",
            help="Max seconds to wait for provisioning before giving up.",
        ),
    ) -> None:
        """Resume a buy from the post-negotiation point.

        Reads the buyer run-log for `<run_id>`, creates the on-chain
        escrow if not already present, POSTs `/settle/{escrow_uid}` to
        the seller, and polls until terminal. Logs each stage transition
        back into the same run-log so a future `market logs show <id>`
        captures the full deal history.

        Requires the run-log to contain an `agreed` negotiation outcome.
        For mid-negotiation resume use `market buy --from <id>` instead.
        """
        # Convert user-friendly hours flag to the wire's seconds.
        duration_seconds_override = (
            round(duration_hours * 3600) if duration_hours is not None else None
        )
        run_settle_from_log(
            run_id=run_id,
            escrow_uid=escrow_uid,
            token_contract=token_contract,
            token_decimals=token_decimals,
            duration_seconds=duration_seconds_override,
            expiration_seconds=expiration_seconds,
            ssh_public_key=ssh_public_key,
            buyer_address=None,
            buyer_private_key=None,
            chain_name=chain_name,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
        )
