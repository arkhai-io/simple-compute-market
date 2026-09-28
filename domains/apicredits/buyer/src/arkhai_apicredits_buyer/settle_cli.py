"""`market credits settle` — composite stages 3-5 of a credit deal.

Resumes a buy from the post-negotiation point: creates the on-chain
escrow if not already created, POSTs `/settle/{escrow_uid}` to the
seller, polls until terminal, and delivers the issued credentials to
the run-log. Driven by a buyer run-log produced by `market credits
negotiate` (or a partially-completed `market credits buy`).

Credit deals are durationless: escrow terms materialize with
``duration_seconds=0`` and the settle request carries an empty
``ssh_public_key`` (the VM domain's provisioning payload).
"""

from __future__ import annotations

import time
import webbrowser
from types import SimpleNamespace
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from market_identity import Signer
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.action_policy import BuyerActionHandler, resolve_buyer_action_policy
from core_buyer.hosted_settlement import HostedSettlementTransport

from .deal_helpers import load_deal_context
from core_buyer.deal_helpers import accepted_settlement_mechanism, open_run_log
from core_buyer.orchestration import (
    DEFAULT_SETTLEMENT_POLL_INTERVAL,
    DEFAULT_SETTLEMENT_TIMEOUT,
    submit_settlement_request,
    wait_for_settlement,
)
from core_buyer.run_log import read_run
from .escrow_client import looks_like_propagation_lag
from market_core.schemas import SettlementPlan
from market_hosted_settlement import FundingMode, FundingSelection
from market_settlement_runtime import derive_obligation_ref

from .hosted_authorization import prepare_hosted_funding_authorization
from .settlement_composition import resolve_buyer_settlement_policy


def _chain_name_from_run_log(run_id: str, *, signer: Signer) -> Optional[str]:
    """Look up the chain the deal targets from signer-bound recovery state."""
    for ev in read_run(run_id, signer=signer):
        if ev.get("event") == "escrow_created":
            cn = ev.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
            terms = ev.get("terms") or {}
            cn = terms.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
        if ev.get("event") == "run_started":
            cn = ev.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
    return None


def _accepted_proposal_chain(deal) -> Optional[str]:
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


def render_credentials(console: Console, credentials: dict) -> None:
    """Show the issued key once — the secret is never returned again.

    The same credentials are appended to the run-log
    (``credentials_delivered``), which is the buyer's durable copy.
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    for label, key in (
        ("Key ID", "key_id"),
        ("Secret", "secret"),
        ("Base URL", "base_url"),
        ("Balance", "balance"),
    ):
        if credentials.get(key) is not None:
            table.add_row(label, str(credentials[key]))
    console.print(
        Panel(
            table,
            title="API key issued — shown once; saved to the run-log",
            border_style="green",
        )
    )


def _hosted_transport_for_deal(
    *,
    identity: ResolvedBuyerIdentity,
    deal,
    log,
) -> HostedSettlementTransport:
    """Bind the accepted listing publisher trust to one shared transport."""
    from .common import (
        resolve_discovery_timeout,
        resolve_indexer_urls,
        resolve_registry_api_keys,
        resolve_registry_authorities,
    )
    from core_buyer.orchestration import make_publisher_trust_resolver
    from core_buyer.orchestrator import BuyConfig

    registry_urls = resolve_indexer_urls()
    registry_authorities = resolve_registry_authorities(registry_urls)
    trust = make_publisher_trust_resolver(
        config=BuyConfig.from_resolved_identity(
            identity=identity,
            registry_urls=registry_urls,
            registry_authorities=registry_authorities,
            discovery_timeout=resolve_discovery_timeout(),
            registry_api_keys=resolve_registry_api_keys(),
        ),
        listing={
            "listing_id": deal.listing_id,
            "publisher_id": deal.publisher_id,
            "publisher_principals": deal.publisher_principals.model_dump(mode="json"),
            "storefront_url": deal.seller_url,
            "source_registry_url": deal.source_registry_url,
            "source_registry_authority": deal.source_registry_authority,
        },
        on_update=lambda event, fields: log.event(event, **fields),
    )
    return HostedSettlementTransport(
        seller_url=deal.seller_url,
        principal=deal.buyer_principal,
        signer=identity.signer,
        resolve_seller_principals=trust,
    )


def _run_hosted_settlement_from_log(
    *,
    run_id: str,
    deal,
    identity: ResolvedBuyerIdentity,
    settlement_ref_override: str | None,
    poll_interval: float,
    settlement_timeout: float,
    funding_mode: str,
    instrument_ref: str | None,
    action: str | None,
    automatic_funding: bool,
    console: Console,
) -> dict:
    """Resume only the accepted hosted operation; never resolve EVM state."""
    plan = SettlementPlan.model_validate(deal.settlement_plan)
    if len(plan.obligations) != 1 or plan.obligations[0].mechanism != "fiat.stripe.v1":
        raise typer.BadParameter("accepted hosted plan is not one exact obligation")
    obligation = plan.obligations[0].model_dump(mode="json")
    obligation_ref = derive_obligation_ref(deal.negotiation_id, 0, obligation)
    try:
        selection = FundingSelection(
            mode=FundingMode(funding_mode),
            instrument_ref=instrument_ref,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    policy = resolve_buyer_settlement_policy(
        identity=identity,
        funding_selection=selection,
        action_capable=action != "fail",
    )
    stripe_config = policy.config.mechanism_config("stripe")
    if stripe_config is None or not stripe_config.enabled:
        raise typer.BadParameter(
            "accepted hosted recovery requires [Settlement.stripe]"
        )
    log = open_run_log(
        run_id,
        signer=identity.signer,
        profile_id=identity.profile_id,
    )
    log.event("settle_resumed")
    transport = _hosted_transport_for_deal(
        identity=identity,
        deal=deal,
        log=log,
    )
    settlement_ref = settlement_ref_override or deal.settlement_ref
    authorization_ref = deal.funding_authorization_ref(obligation_ref)
    if settlement_ref is None:
        if authorization_ref is None:
            authorization = prepare_hosted_funding_authorization(
                buyer_profile_id=str(identity.profile_id),
                principal=deal.buyer_principal,
                signer=identity.signer,
                stripe_config=stripe_config,
                obligation_ref=obligation_ref,
                obligation=obligation,
                selection=selection,
                automatic=automatic_funding,
            )
            authorization_ref = authorization.funding_authorization_ref
            log.event(
                "funding_authorized",
                obligation_ref=obligation_ref,
                funding_profile=authorization.funding_profile.value,
                funding_authorization_ref=authorization_ref,
                expires_at_unix=authorization.expires_at_unix,
            )
        started = transport.start(
            negotiation_id=deal.negotiation_id,
            obligation_ref=obligation_ref,
            funding_authorization_ref=authorization_ref,
        )
        settlement_ref = started.get("settlement_ref")
        if not isinstance(settlement_ref, str) or not settlement_ref:
            raise RuntimeError("storefront returned no hosted settlement reference")
        action_body = started.get("action")
        action_metadata = action_body if isinstance(action_body, dict) else {}
        log.event(
            "settlement_started",
            settlement_ref=settlement_ref,
            obligation_ref=obligation_ref,
            funding_authorization_ref=authorization_ref,
            status=started.get("status"),
            action_kind=action_metadata.get("kind"),
            action_expires_at_unix=action_metadata.get("expires_at_unix"),
        )
    action_policy = resolve_buyer_action_policy(
        action,
        interactive=False,
    )
    action_handler = BuyerActionHandler(
        action_policy,
        open_url=webbrowser.open,
        print_url=typer.echo,
        on_required=lambda metadata: log.event(
            "hosted_checkout_required",
            settlement_ref=settlement_ref,
            action_policy=action_policy.value,
            **metadata.as_event(),
        ),
    )
    try:
        final = transport.resume(
            settlement_ref=settlement_ref,
            poll_interval=poll_interval,
            total_timeout=settlement_timeout,
            on_action=action_handler.handle,
            on_poll=lambda attempt, body: log.event(
                "hosted_settlement_poll",
                attempt=attempt,
                settlement_ref=settlement_ref,
                status=body.get("status"),
                action_kind=(body.get("action") or {}).get("kind"),
                action_expires_at_unix=(body.get("action") or {}).get(
                    "expires_at_unix"
                ),
            ),
            sleep=time.sleep,
        )
    except TimeoutError as exc:
        log.end("timeout", settlement_ref=settlement_ref, reason=str(exc))
        raise typer.Exit(7) from exc
    credentials = final.get("tenant_credentials")
    if isinstance(credentials, dict) and credentials:
        log.event("credentials_delivered", credentials=credentials)
        render_credentials(console, credentials)
    result = final.get("result") or {}
    log.end(
        str(final.get("status") or "unknown"),
        settlement_ref=settlement_ref,
        fulfillment_uid=result.get("fulfillment_id"),
    )
    if final.get("status") not in {"ready", "collected"}:
        raise typer.Exit(7)
    return final


def run_settle_from_log(
    *,
    run_id: str,
    escrow_uid: Optional[str],
    identity: ResolvedBuyerIdentity,
    evm_address: Optional[str],
    evm_private_key: Optional[str],
    chain_name: Optional[str],
    poll_interval: float,
    settlement_timeout: float,
    console: Optional[Console] = None,
    funding_mode: str = "interactive",
    instrument_ref: str | None = None,
    action: str | None = None,
    automatic_funding: bool = False,
) -> dict:
    """Drive stages 3-5 of a credit deal from a buyer run-log.

    Reusable by both ``market credits settle`` and ``market credits buy
    --from``. Reads the run-log for ``run_id``, creates the on-chain
    escrow if not already present, POSTs ``/settle/{escrow_uid}`` to
    the seller, and polls until terminal. Logs each stage transition —
    including the issued credentials — back into the same run-log.

    Returns the final settle-status body. Raises ``typer.Exit`` on
    fatal errors.
    """
    console = console or Console()
    signer = identity.signer
    from .common import (
        chain_by_name,
        make_run_publisher_principals_refresh,
        resolve_buyer_wallet,
        resolve_discovery_timeout,
        resolve_indexer_urls,
        resolve_registry_api_keys,
        resolve_registry_authorities,
    )

    deal = load_deal_context(
        run_id,
        signer=signer,
        refresh_publisher_principals=make_run_publisher_principals_refresh(
            run_id,
            signer=signer,
        ),
    )
    if accepted_settlement_mechanism(deal) == "fiat.stripe.v1":
        return _run_hosted_settlement_from_log(
            run_id=run_id,
            deal=deal,
            identity=identity,
            settlement_ref_override=escrow_uid,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
            funding_mode=funding_mode,
            instrument_ref=instrument_ref,
            action=action,
            automatic_funding=automatic_funding,
            console=console,
        )
    chain_cfg_name = (
        chain_name
        or _accepted_proposal_chain(deal)
        or _chain_name_from_run_log(run_id, signer=signer)
    )
    if not chain_cfg_name:
        typer.secho(
            "Could not determine the chain from the run-log or deal context. "
            "Pass --chain to specify which configured chain to settle on.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain_cfg = chain_by_name(chain_cfg_name)

    if deal.accepted_escrow_proposal is None and deal.accepted_escrow_terms is None:
        typer.secho(
            "Run-log carries no seller-accepted escrow proposal. Re-run "
            "negotiation so the accepted proposal is captured — token "
            "settlement always settles the seller-confirmed shape.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)

    resolved_evm_address, resolved_evm_private_key = resolve_buyer_wallet(
        override_addr=evm_address,
        override_pk=evm_private_key,
    )
    if not resolved_evm_address or not resolved_evm_private_key:
        typer.secho(
            "Missing explicit EVM settlement credentials: wallet.address and "
            "wallet.private_key are required for Alkahest.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain = SimpleNamespace(
        buyer_address=resolved_evm_address,
        buyer_private_key=resolved_evm_private_key,
        rpc_url=chain_cfg.rpc_url,
        chain_name=chain_cfg.name,
        alkahest_addr_config=chain_cfg.alkahest_address_config_path,
    )

    log = open_run_log(
        run_id,
        signer=signer,
        profile_id=identity.profile_id,
    )
    log.event("settle_resumed")
    from core_buyer.orchestration import make_publisher_trust_resolver
    from core_buyer.orchestrator import BuyConfig

    registry_urls = resolve_indexer_urls()
    registry_authorities = resolve_registry_authorities(registry_urls)
    resolve_seller_principals = make_publisher_trust_resolver(
        config=BuyConfig.from_resolved_identity(
            identity=identity,
            registry_urls=registry_urls,
            registry_authorities=registry_authorities,
            discovery_timeout=resolve_discovery_timeout(),
            registry_api_keys=resolve_registry_api_keys(),
        ),
        listing={
            "listing_id": deal.listing_id,
            "publisher_id": deal.publisher_id,
            "publisher_principals": deal.publisher_principals.model_dump(mode="json"),
            "storefront_url": deal.seller_url,
            "source_registry_url": deal.source_registry_url,
            "source_registry_authority": deal.source_registry_authority,
        },
        on_update=lambda event, fields: log.event(event, **fields),
    )

    resolved_uid = escrow_uid or deal.escrow_uid

    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", run_id)
    header.add_row("Seller", deal.seller_url)
    header.add_row("Negotiation", deal.negotiation_id)
    header.add_row("Agreed amount (total)", str(deal.agreed_amount))
    if resolved_uid:
        header.add_row("Escrow UID", resolved_uid + " (skip create)")
    console.print(Panel(header, title="market credits settle", border_style="cyan"))

    # --- Stage 3: escrow.create (skip if uid already known) -------
    if not resolved_uid:
        from market_alkahest.schemas import EscrowProposal, EscrowTerms
        from .escrow_client import (
            make_buyer_payment_escrow_terms_fn,
            make_create_escrow_fn,
        )

        log.event(
            "escrow_create_start",
            terms={
                "seller_url": deal.seller_url,
                "listing_id": deal.listing_id,
                "negotiation_id": deal.negotiation_id,
                "agreed_amount": deal.agreed_amount,
                "duration_seconds": 0,
            },
        )
        console.print("[dim]escrow.create[/dim]  approve + create on-chain…")

        if deal.accepted_escrow_terms is not None:
            escrow_terms_list = [
                EscrowTerms.model_validate(item) for item in deal.accepted_escrow_terms
            ]
        else:
            proposal = EscrowProposal(**deal.accepted_escrow_proposal)
            build_terms = make_buyer_payment_escrow_terms_fn(
                chain_name=chain.chain_name,
                addr_config_path=chain.alkahest_addr_config,
            )
            escrow_terms_list = build_terms(
                proposal,
                deal.seller_wallet_address,
                float(deal.agreed_amount),
                0,  # credit deals fund a quantity, not a lease
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
        log.event(
            "escrow_created", escrow_uid=resolved_uid, chain_name=chain.chain_name
        )
        console.print(f"[green]escrow created[/green]  {resolved_uid}")

    # --- Stage 4: submit settlement -------------------------------
    try:
        submit_body = submit_settlement_request(
            seller_url=deal.seller_url,
            escrow_uid=resolved_uid,
            payload={
                "negotiation_id": deal.negotiation_id,
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
            poll_interval=poll_interval,
            total_timeout=settlement_timeout,
            on_poll=_on_poll,
            resolve_seller_principals=resolve_seller_principals,
        )
    except TimeoutError as exc:
        log.event("settle_terminal", status="timeout", error=str(exc))
        log.end("timeout", escrow_uid=resolved_uid, error=str(exc))
        typer.secho(
            f"settlement polling timed out: {exc}", err=True, fg=typer.colors.YELLOW
        )
        raise typer.Exit(6) from exc

    log.event("settle_terminal", body=final)
    credentials = final.get("tenant_credentials")
    if isinstance(credentials, dict) and credentials:
        # The durable copy — the seller returns the secret exactly once.
        log.event("credentials_delivered", credentials=credentials)
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
    if final.get("reason"):
        result.add_row("Reason", str(final["reason"]))
    border = "green" if final.get("status") == "ready" else "yellow"
    console.print(Panel(result, title="Settlement complete", border_style=border))

    if isinstance(credentials, dict) and credentials:
        render_credentials(console, credentials)

    if final.get("status") != "ready":
        raise typer.Exit(7)

    return final


def _hosted_operation_from_run(
    *,
    run_id: str,
    identity: ResolvedBuyerIdentity,
    operation: str,
    settlement_ref: str | None,
) -> dict:
    """Run one signed provider-neutral status or reclaim request."""
    from .common import make_run_publisher_principals_refresh

    deal = load_deal_context(
        run_id,
        signer=identity.signer,
        refresh_publisher_principals=make_run_publisher_principals_refresh(
            run_id,
            signer=identity.signer,
        ),
    )
    if accepted_settlement_mechanism(deal) != "fiat.stripe.v1":
        raise typer.BadParameter("run did not accept hosted settlement")
    ref = settlement_ref or deal.settlement_ref
    if not ref:
        raise typer.BadParameter("run has no started hosted settlement reference")
    log = open_run_log(
        run_id,
        signer=identity.signer,
        profile_id=identity.profile_id,
    )
    transport = _hosted_transport_for_deal(identity=identity, deal=deal, log=log)
    body = (
        transport.status(settlement_ref=ref)
        if operation == "status"
        else transport.reclaim(settlement_ref=ref)
    )
    action = body.get("action") or {}
    log.event(
        f"hosted_settlement_{operation}",
        settlement_ref=ref,
        status=body.get("status"),
        action_kind=action.get("kind"),
        action_expires_at_unix=action.get("expires_at_unix"),
    )
    credentials = body.get("tenant_credentials")
    if isinstance(credentials, dict) and credentials:
        log.event("credentials_delivered", credentials=credentials)
    return body


def register(credits_app: typer.Typer) -> None:
    """Register `market credits settle`."""

    @credits_app.command("settle-status")
    def settle_status(
        run_id: str = typer.Option(..., "--from", "--run", "-r"),
        settlement_ref: Optional[str] = typer.Option(
            None,
            "--settlement-ref",
            help="Override the opaque reference recorded in the run log.",
        ),
    ) -> None:
        """Fetch the authenticated public hosted state without resuming polls."""
        from .common import resolve_recovery_buyer_identity

        body = _hosted_operation_from_run(
            run_id=run_id,
            identity=resolve_recovery_buyer_identity(run_id),
            operation="status",
            settlement_ref=settlement_ref,
        )
        typer.echo(
            f"{body.get('status', 'unknown')} "
            f"{body.get('settlement_ref', settlement_ref or '')}".rstrip()
        )
        credentials = body.get("tenant_credentials")
        if isinstance(credentials, dict) and credentials:
            render_credentials(Console(), credentials)

    @credits_app.command("reclaim")
    def reclaim(
        run_id: str = typer.Option(..., "--from", "--run", "-r"),
        settlement_ref: Optional[str] = typer.Option(
            None,
            "--settlement-ref",
            help="Override the opaque reference recorded in the run log.",
        ),
    ) -> None:
        """Request reclaim only for the run's exact unfulfilled obligation."""
        from .common import resolve_recovery_buyer_identity

        body = _hosted_operation_from_run(
            run_id=run_id,
            identity=resolve_recovery_buyer_identity(run_id),
            operation="reclaim",
            settlement_ref=settlement_ref,
        )
        typer.echo(
            f"{body.get('status', 'unknown')} "
            f"{body.get('settlement_ref', settlement_ref or '')}".rstrip()
        )

    @credits_app.command("settle")
    def settle(
        run_id: str = typer.Option(
            ...,
            "--from",
            "--run",
            "-r",
            help="Buyer run-id from a prior `market credits negotiate` to "
            "resume from (see the buy-runs log directory).",
        ),
        escrow_uid: Optional[str] = typer.Option(
            None,
            "--escrow-uid",
            "-u",
            help="Skip escrow.create when the on-chain escrow already exists. "
            "If absent, the run-log is checked for an `escrow_created` event.",
        ),
        evm_address: Optional[str] = typer.Option(
            None,
            "--evm-address",
            help="EVM address required for the Alkahest settlement effect.",
        ),
        evm_private_key: Optional[str] = typer.Option(
            None,
            "--evm-private-key",
            help="EVM private key required only for Alkahest escrow creation.",
        ),
        chain_name: Optional[str] = typer.Option(
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
            help="Max seconds to wait for issuance before giving up.",
        ),
        funding_mode: str = typer.Option(
            "interactive",
            "--funding-mode",
            help="Hosted recovery mode: interactive or saved_instrument.",
        ),
        instrument_ref: Optional[str] = typer.Option(
            None,
            "--instrument-ref",
            help="Opaque instrument reference for a not-yet-authorized saved payment.",
        ),
        action: Optional[str] = typer.Option(
            None,
            "--action",
            help="Transient hosted-action policy: open, print, or fail.",
        ),
        automatic_funding: bool = typer.Option(
            False,
            "--automatic-funding",
            help="Evaluate the exact bounded off-session authorization policy.",
        ),
    ) -> None:
        """Resume a credit buy from the post-negotiation point.

        Reads the buyer run-log for `<run_id>`, creates the on-chain
        escrow if not already present, POSTs `/settle/{escrow_uid}` to
        the seller, and polls until terminal. The issued credentials
        land in the same run-log (``credentials_delivered``) — the
        seller returns the secret exactly once.

        Requires the run-log to contain an `agreed` negotiation outcome.
        """
        from .common import resolve_recovery_buyer_identity

        identity = resolve_recovery_buyer_identity(run_id)
        run_settle_from_log(
            run_id=run_id,
            escrow_uid=escrow_uid,
            identity=identity,
            evm_address=evm_address,
            evm_private_key=evm_private_key,
            chain_name=chain_name,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
            funding_mode=funding_mode,
            instrument_ref=instrument_ref,
            action=action,
            automatic_funding=automatic_funding,
        )
