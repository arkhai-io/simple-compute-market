"""Resume an accepted settlement and provisioning lifecycle.

The accepted plan selects the mechanism. Hosted Stripe recovery starts or
resumes its opaque settlement reference and applies the configured buyer
action policy. Alkahest recovery creates the accepted on-chain obligation when
needed, submits it to the seller, and polls the deal to terminal state.

Raw Alkahest inspection and mutation remain under
``market settlement alkahest escrow``.
"""

from __future__ import annotations

import os
import webbrowser
from types import SimpleNamespace

import typer
from arkhai_vms.provision_terms import VmProvisionPayload, VmProvisionTerms
from market_core.schemas import SettlementPlan
from market_identity import Identity
from market_settlement_runtime import derive_obligation_ref
from market_hosted_settlement import FundingMode, FundingSelection, StripeSettlementConfig
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.action_policy import (
    ACTION_REQUIRED_EXIT_CODE,
    BuyerActionHandler,
    BuyerActionPolicy,
    BuyerActionRequired,
    resolve_buyer_action_policy,
)
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
from .hosted_authorization import prepare_hosted_funding_authorization
from .settlement_composition import resolve_buyer_settlement_policy
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


def _is_legacy_hosted_recovery(obligation: dict) -> bool:
    params = obligation.get("params")
    if not isinstance(params, dict):
        return False
    methods = params.get("payment_method_types")
    if methods is None:
        return False
    if methods != ["card"] or "funding_profile" in params:
        raise ValueError("accepted hosted settlement has ambiguous legacy funding")
    return True


def _accepted_provision_inputs(deal) -> tuple[str | None, int]:
    """Recover immutable provision inputs, reserving config for legacy absence."""

    raw = deal.accepted_provision_terms
    if raw is None:
        if deal.settlement_selection is not None or deal.settlement_plan is not None:
            raise typer.BadParameter(
                "accepted settlement state omitted accepted_provision_terms; "
                "current configuration will not reinterpret this run"
            )
        return None, int(deal.duration_seconds)
    try:
        if isinstance(raw, dict) and "payload" in raw:
            payload = VmProvisionTerms.model_validate(raw).payload
            accepted = VmProvisionPayload.model_validate(payload)
        else:
            accepted = VmProvisionPayload.model_validate(raw)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(
            "run-log has malformed accepted VM provision terms"
        ) from exc
    ssh_public_key = accepted.ssh_public_key.strip()
    if not ssh_public_key:
        raise typer.BadParameter(
            "accepted VM provision terms have no SSH public key; current "
            "configuration will not reinterpret this run"
        )
    return ssh_public_key, accepted.duration_seconds


def run_settle_from_log(
    *,
    run_id: str,
    poll_interval: float,
    settlement_timeout: float,
    console: Console | None = None,
    action_policy: BuyerActionPolicy | None = None,
    identity: ResolvedBuyerIdentity | None = None,
    funding_mode: FundingMode = FundingMode.INTERACTIVE,
    instrument_ref: str | None = None,
    automatic_funding: bool = False,
) -> dict:
    """Resume one accepted deal from its buyer run log.

    Reusable by both ``market settle`` and ``market buy --from``. The accepted
    mechanism and operation identities remain authoritative: hosted recovery
    resumes its opaque reference, while Alkahest recovery creates a missing
    accepted escrow. Both paths persist transitions to the same run log and
    drive the seller lifecycle to a terminal state.

    Returns the final status body. Raises ``typer.Exit`` on fatal resolution,
    mechanism, provider/chain, timeout, or non-ready terminal failures.
    """
    console = console or Console()
    from .common import chain_by_name, resolve_recovery_buyer_identity

    identity = identity or resolve_recovery_buyer_identity(run_id)
    signer = identity.signer
    deal = load_deal_context(run_id, signer=signer)
    resolve_seller_principals = make_deal_publisher_trust_resolver(run_id, deal, signer)
    log = open_run_log(
        run_id,
        signer=signer,
        profile_id=identity.profile_id,
    )
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
        settlement_ref = deal.settlement_ref
        try:
            legacy_hosted_recovery = _is_legacy_hosted_recovery(hosted_obligation)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if legacy_hosted_recovery and settlement_ref is None:
            raise typer.BadParameter(
                "historical hosted card settlement has no recoverable settlement "
                "reference; operator recovery is required"
            )
        funding_authorization_ref = deal.funding_authorization_ref(obligation_ref)
        if settlement_ref is None and funding_authorization_ref is None:
            try:
                selection = FundingSelection(
                    mode=funding_mode,
                    instrument_ref=instrument_ref,
                )
                stripe_config = StripeSettlementConfig.model_validate(
                    resolve_buyer_settlement_policy()
                    .config.mechanism_config("stripe")
                )
                authorization = prepare_hosted_funding_authorization(
                    buyer_profile_id=str(identity.profile_id),
                    principal=deal.buyer_principal,
                    signer=signer,
                    stripe_config=stripe_config,
                    obligation_ref=obligation_ref,
                    obligation=hosted_obligation,
                    selection=selection,
                    automatic=automatic_funding,
                )
            except BuyerActionRequired as exc:
                typer.secho(str(exc), err=True, fg=typer.colors.YELLOW)
                raise typer.Exit(ACTION_REQUIRED_EXIT_CODE) from exc
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            funding_authorization_ref = authorization.funding_authorization_ref
            log.event(
                "funding_authorized",
                obligation_ref=obligation_ref,
                funding_profile=authorization.funding_profile.value,
                funding_authorization_ref=funding_authorization_ref,
                expires_at_unix=authorization.expires_at_unix,
            )
        started: dict | None = None
        if settlement_ref is None:
            started = start_hosted_settlement(
                seller_url=deal.seller_url,
                negotiation_id=deal.negotiation_id,
                obligation_ref=obligation_ref,
                funding_authorization_ref=funding_authorization_ref,
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

        resolved_action_policy = action_policy or BuyerActionPolicy.PRINT

        def _open_action_url(url: str) -> None:

            console.print("[dim]opening buyer settlement action[/dim]")
            webbrowser.open(url)

        action_handler = BuyerActionHandler(
            resolved_action_policy,
            open_url=_open_action_url,
            print_url=lambda url: console.print(url, markup=False),
            on_required=lambda metadata: log.event(
                "hosted_checkout_required",
                settlement_ref=settlement_ref,
                action_policy=resolved_action_policy.value,
                **metadata.as_event(),
            ),
        )
        if started is not None and isinstance(started.get("action"), dict):
            try:
                action_handler.handle(started["action"])
            except BuyerActionRequired as exc:
                typer.secho(str(exc), err=True, fg=typer.colors.YELLOW)
                raise typer.Exit(ACTION_REQUIRED_EXIT_CODE) from exc

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

        try:
            final = wait_for_hosted_settlement(
                seller_url=deal.seller_url,
                settlement_ref=settlement_ref,
                principal=deal.buyer_principal,
                signer=signer,
                poll_interval=poll_interval,
                total_timeout=settlement_timeout,
                on_poll=_hosted_poll,
                on_action=action_handler.handle,
                resolve_seller_principals=resolve_seller_principals,
            )
        except BuyerActionRequired as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.YELLOW)
            raise typer.Exit(ACTION_REQUIRED_EXIT_CODE) from exc
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
    accepted_ssh_public_key, effective_duration = _accepted_provision_inputs(deal)

    effective_token = deal.token_contract
    effective_token_decimals: int | None = (
        int(deal.token_decimals) if deal.token_decimals is not None else None
    )
    chain_cfg_name = (
        _accepted_proposal_chain(deal)
        or _chain_name_from_run_log(run_id, signer=signer)
        or _first_listing_chain(deal)
    )
    if not chain_cfg_name:
        typer.secho(
            "Could not derive the selected EVM chain from accepted state.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain_cfg = chain_by_name(chain_cfg_name)
    if deal.accepted_escrow_proposal is not None:
        from .common import resolve_buyer_wallet, resolve_ssh_public_key

        resolved_buyer_address, resolved_buyer_private_key = resolve_buyer_wallet()
        resolved_ssh_public_key = (
            accepted_ssh_public_key
            if accepted_ssh_public_key is not None
            else resolve_ssh_public_key()
        )
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
            buyer_address=None,
            buyer_private_key=None,
            ssh_public_key=accepted_ssh_public_key,
            chain=chain_cfg,
            token_contract=effective_token,
            token_decimals=effective_token_decimals,
        )
        chain.alkahest_addr_config = alkahest_address_config_path

    resolved_uid = deal.escrow_uid

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
                expiration_unix=int(_time.time()) + 3600,
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
            help="Buyer run-id with an accepted settlement to resume "
            "(see `market logs runs`).",
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
        action: BuyerActionPolicy | None = typer.Option(
            None,
            "--action",
            help="Handle transient settlement actions: open, print, or fail. "
            "Defaults to open in an interactive terminal and print otherwise.",
        ),
        funding_mode: FundingMode = typer.Option(
            FundingMode.INTERACTIVE,
            "--funding-mode",
            help="Hosted payer mode when this run has no authorization yet.",
        ),
        instrument_ref: str | None = typer.Option(
            None,
            "--instrument-ref",
            help="Transient opaque saved-instrument ref; never written to the run log.",
        ),
        automatic_funding: bool = typer.Option(
            False,
            "--automatic-funding",
            help="Apply the disabled-by-default bounded off-session policy.",
        ),
    ) -> None:
        """Resume a buy from the post-negotiation point.

        Reads the accepted settlement from the buyer run-log, starts or resumes
        its pinned obligation, submits fulfillment to the seller, and polls until
        terminal. The same run-log is appended throughout.

        Requires the run-log to contain an accepted negotiation outcome.
        For mid-negotiation resume use `market buy --from <id>` instead.
        """

        action_policy = resolve_buyer_action_policy(
            action,
            interactive=os.isatty(0) and os.isatty(1),
        )
        run_settle_from_log(
            run_id=run_id,
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
            action_policy=action_policy,
            funding_mode=funding_mode,
            instrument_ref=instrument_ref,
            automatic_funding=automatic_funding,
        )
