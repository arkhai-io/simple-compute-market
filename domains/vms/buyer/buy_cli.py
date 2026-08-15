"""`market buy` — pure-client sequential buy.

No buyer agent, no event pipeline. Drives the deal end-to-end from the
CLI process:

    discover (registry) →
    negotiate each match (sync HTTP rounds) →
    pick agreed match →
    create escrow on-chain (alkahest-py in-process) →
    POST /settle/{uid} on seller →
    poll /settle/{uid}/status until ready/failed.

The orchestrator itself is in market.buy_orchestrator; this command
just wires env → config → call.
"""

from __future__ import annotations

import json
import os
import time
import webbrowser
from collections.abc import Callable
from typing import Any
from core_buyer import build_buyer_explanation, explain_registry_query
from core_buyer.action_policy import (
    ACTION_REQUIRED_EXIT_CODE,
    BuyerActionHandler,
    BuyerActionPolicy,
    BuyerActionRequired,
    resolve_buyer_action_policy,
)
from core_buyer.orchestration import (
    make_publisher_trust_resolver as make_core_publisher_trust_resolver,
)

import typer
from arkhai_vms import make_vm_provision_terms
from market_alkahest.schemas import EscrowProposal
from market_alkahest.token import TokenResolutionError, resolve_token
from market_identity import Identity
from market_core.schemas import SettlementSelection
from market_settlement_runtime import derive_obligation_ref
from market_hosted_settlement import (
    FundingMode,
    FundingSelection,
    StripeSettlementConfig,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from domains.vms.settlement import escrow_proposal_from_accepted_entry

from .buy_orchestrator import (
    BuyConfig,
    BuyConstraints,
    BuyResult,
    make_legacy_negotiate_hook,
    make_legacy_settle_hook,
    query_registry_for_matches_multi,
    run_buy,
)
from .buyer_client import ResumeState, negotiate_with_seller
from .settlement_composition import (
    resolve_buyer_settlement_policy,
    revalidate_hosted_buyer_option,
)
from .common import resolve_config_value
from .cli_helpers import (
    emit_buyer_explanation,
    resolve_prices_from_matches as _resolve_prices_from_matches,
)
from .deal_helpers import (
    is_negotiation_complete,
    load_negotiation_resume_point,
    make_publisher_trust_resolver,
    open_run_log,
)
from .listing_cli import settlement_clause_error_message
from .hosted_settlement import (
    start_hosted_settlement,
    wait_for_hosted_settlement,
)
from .hosted_authorization import prepare_hosted_funding_authorization
from .run_log import RunLog
from .settle_cli import run_settle_from_log


def _normalize_start_utc(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "now":
        return None
    return text


def _make_hosted_settle_hook(
    *,
    config: BuyConfig,
    provision: Any,
    poll_interval: float,
    total_timeout: float,
    sleep: Callable[[float], None],
    action_policy: BuyerActionPolicy,
    open_url: Callable[[str], Any],
    print_url: Callable[[str], Any],
    stripe_config: StripeSettlementConfig,
    funding_selection: FundingSelection,
    automatic_funding: bool,
    confirm: Callable[[int, dict[str, Any]], bool] | None = None,
):
    del provision

    def _hook(negotiation, on_event):
        outcome = negotiation.outcome
        match = negotiation.match
        if outcome is None or match is None or outcome.settlement_plan is None:
            raise ValueError("hosted settlement requires an accepted settlement plan")
        obligations = outcome.settlement_plan.obligations
        if len(obligations) != 1 or obligations[0].mechanism != "fiat.stripe.v1":
            raise ValueError("hosted settlement requires one fiat.stripe.v1 obligation")

        resolve_seller_principals = make_core_publisher_trust_resolver(
            config=config,
            listing=match,
            on_update=lambda stage, payload: on_event(stage, payload),
        )
        obligation = obligations[0].model_dump(mode="json")
        if confirm is not None and not confirm(int(obligation["amount"]), match):
            return BuyResult(
                status="exited",
                negotiation_id=outcome.negotiation_id,
                seller_url=str(match.get("storefront_url") or ""),
                agreed_amount=outcome.agreed_amount,
                reason="user_declined",
                rounds=outcome.rounds,
                attempts=negotiation.attempts,
            )
        negotiation_id = outcome.negotiation_id or ""
        obligation_ref = derive_obligation_ref(negotiation_id, 0, obligation)
        authorization = prepare_hosted_funding_authorization(
            buyer_profile_id=str(config.buyer_profile_id),
            principal=config.principal,
            signer=config.signer,
            stripe_config=stripe_config,
            obligation_ref=obligation_ref,
            obligation=obligation,
            selection=funding_selection,
            automatic=automatic_funding,
        )
        on_event(
            "funding_authorized",
            {
                "obligation_ref": obligation_ref,
                "funding_profile": authorization.funding_profile.value,
                "funding_authorization_ref": authorization.funding_authorization_ref,
                "expires_at_unix": authorization.expires_at_unix,
            },
        )
        seller_url = str(match.get("storefront_url") or "")
        if not seller_url:
            raise ValueError("listing is missing required storefront_url")
        started = start_hosted_settlement(
            seller_url=seller_url,
            negotiation_id=negotiation_id,
            obligation_ref=obligation_ref,
            funding_authorization_ref=authorization.funding_authorization_ref,
            principal=config.principal,
            signer=config.signer,
            resolve_seller_principals=resolve_seller_principals,
        )
        settlement_ref = started.get("settlement_ref")
        if not isinstance(settlement_ref, str) or not settlement_ref:
            raise RuntimeError(
                "storefront returned no opaque hosted settlement reference"
            )
        action_handler = BuyerActionHandler(
            action_policy,
            open_url=open_url,
            print_url=print_url,
            on_required=lambda metadata: on_event(
                "hosted_checkout_required",
                {
                    "settlement_ref": settlement_ref,
                    "action_policy": action_policy.value,
                    **metadata.as_event(),
                },
            ),
        )

        initial_action = started.get("action")
        public_action = initial_action if isinstance(initial_action, dict) else {}
        on_event(
            "settlement_started",
            {
                "settlement_ref": settlement_ref,
                "status": started.get("status"),
                "action_kind": public_action.get("kind"),
                "action_expires_at_unix": public_action.get("expires_at_unix"),
            },
        )
        if public_action:
            action_handler.handle(public_action)
        try:
            final = wait_for_hosted_settlement(
                seller_url=seller_url,
                settlement_ref=settlement_ref,
                principal=config.principal,
                signer=config.signer,
                resolve_seller_principals=resolve_seller_principals,
                poll_interval=poll_interval,
                total_timeout=total_timeout,
                on_action=action_handler.handle,
                on_poll=lambda attempt, body: on_event(
                    "hosted_settlement_poll",
                    {
                        "attempt": attempt,
                        "settlement_ref": settlement_ref,
                        "status": body.get("status"),
                        "action_kind": (body.get("action") or {}).get("kind"),
                        "action_expires_at_unix": (body.get("action") or {}).get(
                            "expires_at_unix"
                        ),
                    },
                ),
                sleep=sleep,
            )
        except TimeoutError as exc:
            return BuyResult(
                status="timeout",
                negotiation_id=negotiation_id,
                seller_url=seller_url,
                agreed_amount=outcome.agreed_amount,
                escrow_uid=settlement_ref,
                reason=str(exc),
                rounds=outcome.rounds,
                attempts=negotiation.attempts,
            )
        succeeded = final.get("status") in {"ready", "collected"}
        return BuyResult(
            status="ready" if succeeded else "failed",
            negotiation_id=negotiation_id,
            seller_url=seller_url,
            agreed_amount=outcome.agreed_amount,
            escrow_uid=settlement_ref,
            reason=None if succeeded else "hosted_settlement_not_completed",
            rounds=outcome.rounds,
            attempts=negotiation.attempts,
        )

    return _hook


def _confirm_settlement_interactive(*, terms, listing: dict, console: Console) -> bool:
    """Prompt the buyer to approve settlement at the negotiated price.

    Shown after negotiation agrees but BEFORE create_escrow runs — i.e.,
    no on-chain transaction has been emitted and the seller's /settle
    endpoint hasn't been touched yet. Declining here is a clean exit.

    Displays the agreed per-hour rate, duration, total payment (= rate
    x duration_seconds / 3600), seller URL, and listing ID so the buyer
    can sanity-check the cost before committing.
    """
    duration_hours = terms.duration_seconds / 3600
    total = terms.agreed_amount * terms.duration_seconds // 3600
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Seller", str(terms.seller_url))
    table.add_row("Listing", str(terms.listing_id))
    table.add_row("Negotiation", str(terms.negotiation_id))
    table.add_row("Agreed price", f"{terms.agreed_amount} (per hour, raw token units)")
    table.add_row("Duration", f"{terms.duration_seconds}s ({duration_hours:.4g}h)")
    table.add_row("Total payment", f"{total} (raw token units)")
    console.print(Panel(table, title="Confirm settlement", border_style="yellow"))
    try:
        return typer.confirm(
            "Proceed to settlement (escrow + /settle + poll)?", default=True
        )
    except typer.Abort:
        return False


def _run_resume_from(
    *,
    from_run: str,
    max_price: float | None,
    max_rounds: int,
    poll_interval: float,
    settlement_timeout: float,
    console: Console,
    action_policy: BuyerActionPolicy,
    funding_mode: FundingMode,
    instrument_ref: str | None,
    automatic_funding: bool,
) -> None:
    """Composite resume: finish negotiation if mid-stream, then settle.

    The same run-log is appended throughout — fresh `negotiate`-style
    events when finishing the negotiation, then `settle_*` events from
    ``run_settle_from_log``.
    """
    from .common import resolve_recovery_buyer_identity

    identity = resolve_recovery_buyer_identity(from_run)
    signer = identity.signer
    if not is_negotiation_complete(from_run, signer=signer):
        if max_price is not None:
            raise typer.BadParameter(
                "--max-price applies only to fresh buys; resume uses the "
                "persisted scaled negotiation ceiling"
            )

        resume_point = load_negotiation_resume_point(from_run, signer=signer)
        resumed_initial_price = resume_point.initial_price
        resumed_max_price = resume_point.max_price
        run_log = open_run_log(
            from_run,
            signer=signer,
            profile_id=identity.profile_id,
        )
        run_log.event(
            "negotiation_resumed",
            from_run=from_run,
            negotiation_id=resume_point.negotiation_id,
            rounds_completed=resume_point.rounds_completed,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", from_run)
        header.add_row("Mode", "resume (mid-negotiation)")
        header.add_row("Seller", resume_point.seller_url)
        header.add_row("Listing", resume_point.listing_id)
        header.add_row("Negotiation", resume_point.negotiation_id)
        header.add_row("Rounds completed", str(resume_point.rounds_completed))
        header.add_row("Ceiling", str(resumed_max_price))
        console.print(Panel(header, title="market buy --from", border_style="cyan"))

        def _observe(round_idx: int, our_msg: dict, reply: dict) -> None:
            run_log.event(
                "negotiation_round",
                round=round_idx,
                our_message=our_msg,
                their_reply=reply,
            )
            their = reply or {}
            console.print(
                f"[dim]  round {round_idx}[/dim]  → "
                f"{their.get('action', '-')} @ {their.get('price', '-')}"
            )

        resume_chain = None
        if getattr(resume_point, "policy", None):
            from .buyer_client import load_buyer_chain

            resume_chain = load_buyer_chain(
                policy_mode=str(resume_point.policy),
            )
        resolve_seller_principals = make_publisher_trust_resolver(
            run_id=from_run,
            listing_id=resume_point.listing_id,
            publisher_id=resume_point.publisher_id,
            source_registry_url=resume_point.source_registry_url,
            source_registry_authority=resume_point.source_registry_authority,
            current=resume_point.publisher_principals,
            signer=signer,
        )

        try:
            outcome = negotiate_with_seller(
                seller_url=resume_point.seller_url,
                principal=resume_point.buyer_principal,
                signer=signer,
                listing_id=resume_point.listing_id,
                initial_price=resumed_initial_price,
                max_price=resumed_max_price,
                max_rounds=max_rounds,
                chain=resume_chain,
                on_round=_observe,
                resume=ResumeState(
                    negotiation_id=resume_point.negotiation_id,
                    transcript=resume_point.transcript,
                    last_seller_proposal=resume_point.last_seller_proposal,
                    rounds_completed=resume_point.rounds_completed,
                    accepted_provision_terms=resume_point.accepted_provision_terms,
                    accepted_escrow_proposal=resume_point.accepted_escrow_proposal,
                    settlement_selection=resume_point.settlement_selection,
                    settlement_plan=resume_point.settlement_plan,
                    accepted_escrow_terms=resume_point.accepted_escrow_terms,
                ),
                resolve_seller_principals=resolve_seller_principals,
            )
        except RuntimeError as exc:
            run_log.event("negotiation_failed", error=str(exc))
            run_log.end("error", error=str(exc))
            typer.secho(
                f"Resumed negotiation failed: {exc}", err=True, fg=typer.colors.RED
            )
            raise typer.Exit(3) from exc

        from core_buyer.deal_helpers import settlement_acceptance_fields

        accepted_settlement = settlement_acceptance_fields(
            negotiation_id=outcome.negotiation_id or "",
            selection=outcome.settlement_selection,
            plan=outcome.settlement_plan,
        )
        run_log.event(
            "negotiation_completed",
            seller_url=resume_point.seller_url,
            status=outcome.status,
            agreed_amount=outcome.agreed_amount,
            rounds=outcome.rounds,
            reason=outcome.reason,
            negotiation_id=outcome.negotiation_id,
            listing_id=resume_point.listing_id,
            accepted_escrow_proposal=(
                outcome.accepted_escrow_proposal.model_dump()
                if outcome.accepted_escrow_proposal is not None
                else None
            ),
            **accepted_settlement,
            accepted_escrow_terms=(
                [term.model_dump() for term in outcome.accepted_escrow_terms]
                if outcome.accepted_escrow_terms is not None
                else None
            ),
            accepted_provision_terms=(
                outcome.accepted_provision_terms.model_dump()
                if outcome.accepted_provision_terms is not None
                else None
            ),
        )

        if outcome.status != "agreed" or outcome.agreed_amount is None:
            run_log.end(
                outcome.status,
                negotiation_id=outcome.negotiation_id,
                rounds=outcome.rounds,
                reason=outcome.reason,
            )
            color = "yellow" if outcome.status == "exited" else "red"
            typer.secho(
                f"Negotiation did not agree (status={outcome.status}, "
                f"reason={outcome.reason!r}). Settlement skipped.",
                err=True,
                fg=getattr(typer.colors, color.upper(), typer.colors.YELLOW),
            )
            raise typer.Exit(4)

        console.print(
            f"[green]negotiation agreed[/green]  price={outcome.agreed_amount} "
            f"rounds={outcome.rounds}"
        )

    run_settle_from_log(
        run_id=from_run,
        poll_interval=poll_interval,
        settlement_timeout=settlement_timeout,
        console=console,
        action_policy=action_policy,
        identity=identity,
        funding_mode=funding_mode,
        instrument_ref=instrument_ref,
        automatic_funding=automatic_funding,
    )


def register(app: typer.Typer) -> None:
    """Register the top-level `market buy` command.

    Pricing flags are not defined here: the configured negotiation
    policy contributes its own parameter surface at app-assembly time
    (ARCHITECTURE.md, "Buyer negotiation policy surface") — the scalar policies
    contribute --initial-price/--max-price/--price-markup, so the
    default surface is unchanged; a different policy contributes
    different knobs, plus the --policy-param escape hatch.
    """
    from core_buyer.cli import (
        assume_yes_option,
        parse_key_value_options,
        register_policy_verb,
    )

    from .policy_surface import configured_buyer_policy

    _policy = configured_buyer_policy()

    def buy(  # registered below after policy-param injection
        assume_yes: bool = assume_yes_option(
            "Skip ALL interactive prompts (price defaults + "
            "pre-settlement confirmation). Same effect as running "
            "without a TTY — defaults are accepted automatically. "
            "Set this for scripts, CI, or non-interactive runs.",
        ),
        quiet: bool = typer.Option(
            False,
            "--quiet",
            "-q",
            help="Condensed output: drop the per-step progress panels and "
            "print one concise summary (deal, escrow, VM, connection) "
            "when the buy settles. Provisioning shows a simple progress "
            "line. Good for scripts and clean terminals.",
        ),
        duration_hours: float | None = typer.Option(
            None,
            "--duration-hours",
            "-t",
            help="Lease duration the buyer wants (hours, fractional ok). "
            "Required for fresh runs — sent to the seller's "
            "/negotiate/new and validated against the listing's "
            "max_duration_seconds. Resumed runs read it from the run-log.",
        ),
        start_utc: str | None = typer.Option(
            None,
            "--start-utc",
            help="Requested lease start time in UTC (ISO-8601 or YYYY-MM-DD HH:MM). "
            "Omit or pass 'now' for immediate start.",
        ),
        resource_query: str | None = typer.Option(
            None,
            "--resource",
            help="Typed resource constraints, for example "
            "'gpu_model in [H200,A100] ram_gb>=64 static_ip=true'.",
        ),
        from_run: str | None = typer.Option(
            None,
            "--from",
            help="Resume a partial buy run-id end-to-end. Continues "
            "negotiation if it stopped mid-stream, then drives "
            "escrow.create + /settle + poll. The same run-log is "
            "appended to so `market logs show <id>` captures the "
            "full lifecycle.",
        ),
        registry_urls: str | None = typer.Option(
            None,
            "--registry-urls",
            help="Comma-separated registry base URLs (default: "
            "registry.urls from config.toml). Discovery is the "
            "union across all listed registries, deduped by listing_id.",
        ),
        discovery_timeout: float | None = typer.Option(
            None,
            "--discovery-timeout",
            help="Per-registry deadline in seconds (default: "
            "registry.discovery_timeout from config.toml, fallback 5).",
        ),
        settlement: list[str] | None = typer.Option(
            None,
            "--settlement",
            help="Repeatable typed settlement alternative, for example "
            "'mechanism=stripe asset=usd stripe.method=card'.",
        ),
        explain: bool = typer.Option(
            False,
            "--explain",
            help="Render a read-only selection plan and stop before negotiation.",
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
            help="Hosted payer mode: interactive or saved_instrument.",
        ),
        instrument_ref: str | None = typer.Option(
            None,
            "--instrument-ref",
            help="Opaque saved-instrument ref; transient and never written to the run log.",
        ),
        automatic_funding: bool = typer.Option(
            False,
            "--automatic-funding",
            help="Apply the disabled-by-default bounded off-session policy.",
        ),
        expiration_seconds: int = typer.Option(
            3600,
            "--expiration",
            help="Escrow deadline (seconds from now) for the "
            "reclaim_expired escape hatch. Default 1h.",
        ),
        max_matches: int = typer.Option(
            5,
            "--max-matches",
            help="How many matching seller orders to try before giving up.",
        ),
        aggregate_by: str | None = typer.Option(
            None,
            "--aggregate-by",
            help="Across-seller aggregation policy. Default: "
            "[aggregation].policy from buyer.toml, falling "
            "back to 'best_price'. Built-ins: best_price, "
            "fastest_agreed, cheapest_first, registry_order, "
            "random_shuffle, priceless_last.",
        ),
        max_rounds: int = typer.Option(
            10,
            "--max-rounds",
            help="Per-negotiation round cap.",
        ),
        poll_interval: float = typer.Option(
            5.0,
            "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            600.0,
            "--settlement-timeout",
            help="Max seconds to wait for provisioning before giving up.",
        ),
        ssh_public_key: str | None = typer.Option(
            None,
            "--ssh-public-key",
            help="SSH public key for provisioning (default: wallet.ssh_public_key).",
        ),
        **policy_values: Any,
    ) -> None:
        """Run or resume a complete buyer lifecycle without a buyer daemon.

        Discovery and negotiation use authenticated registry and seller HTTP
        calls. The accepted settlement plan then dispatches to its installed
        hosted or Alkahest mechanism; any required buyer interaction follows
        ``--action``.

        ``--from <run_id>`` resumes the recorded negotiation and accepted
        settlement identities rather than discovering or buying again.
        """
        console = Console()
        action_policy = resolve_buyer_action_policy(
            action,
            interactive=os.isatty(0) and os.isatty(1),
        )
        try:
            funding_selection = FundingSelection(
                mode=funding_mode,
                instrument_ref=instrument_ref,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--funding-mode") from exc
        if automatic_funding and funding_mode is not FundingMode.SAVED_INSTRUMENT:
            raise typer.BadParameter(
                "--automatic-funding requires --funding-mode saved_instrument"
            )

        # The configured policy's parameters arrive through the injected
        # flags. They live in one policy-owned namespace: declared flag
        # values merged with parsed --policy-param pairs.
        policy_params_all: dict[str, Any] = {
            k: v for k, v in policy_values.items() if k != "policy_param"
        }
        policy_params_all.update(
            parse_key_value_options(
                policy_values.get("policy_param") or [],
                option_name="--policy-param",
            )
        )
        # The scalar names the rest of this body needs:
        initial_price: float | None = policy_params_all.get("initial_price")
        max_price: float | None = policy_params_all.get("max_price")

        if from_run:
            if explain:
                raise typer.BadParameter(
                    "--explain applies to fresh discovery; it cannot resume a run"
                )
            _run_resume_from(
                from_run=from_run,
                max_price=max_price,
                max_rounds=max_rounds,
                poll_interval=poll_interval,
                settlement_timeout=settlement_timeout,
                console=console,
                action_policy=action_policy,
                funding_mode=funding_mode,
                instrument_ref=instrument_ref,
                automatic_funding=automatic_funding,
            )
            return

        if not explain and (duration_hours is None or duration_hours <= 0):
            typer.secho(
                "Fresh `market buy` runs require --duration-hours "
                "(the buyer's lease ask).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        duration_seconds = (
            round(duration_hours * 3600) if duration_hours is not None else 0
        )
        requested_start_utc = _normalize_start_utc(start_utc)

        explicit_prices = initial_price is not None and max_price is not None
        if not explain and (initial_price is not None) != (max_price is not None):
            typer.secho(
                "Pass both --initial-price and --max-price, or neither "
                "(in which case prices are derived from seller min_price).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        from .common import (
            VMS_SCHEMA_ID,
            resolve_buyer_wallet,
            resolve_fresh_buyer_identity,
            resolve_discovery_timeout,
            resolve_indexer_urls,
            resolve_indexer_urls_for_schema,
            resolve_registry_api_keys,
            resolve_registry_authorities,
            resolve_ssh_public_key,
        )

        identity = resolve_fresh_buyer_identity()
        signer = identity.signer
        ssh = None if explain else resolve_ssh_public_key(override=ssh_public_key)
        try:
            settlement_policy = resolve_buyer_settlement_policy(
                identity=identity,
                funding_selection=funding_selection,
                action_capable=action_policy is not BuyerActionPolicy.FAIL,
            )
        except ValueError as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(2) from exc
        try:
            settlement_clauses = settlement_policy.compile_clauses(settlement or ())
        except ValueError as exc:
            typer.secho(
                settlement_clause_error_message(exc, settlement_policy),
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2) from exc
        configured_reg_urls = resolve_indexer_urls(override=registry_urls)
        registry_authorities = resolve_registry_authorities(configured_reg_urls)
        deadline = resolve_discovery_timeout(override=discovery_timeout)
        reg_urls = resolve_indexer_urls_for_schema(
            VMS_SCHEMA_ID,
            signer=signer,
            registry_authorities=registry_authorities,
            override=registry_urls,
            timeout=deadline,
        )
        registry_authorities = {url: registry_authorities[url] for url in reg_urls}
        registry_api_keys = {
            url: key
            for url, key in resolve_registry_api_keys().items()
            if url in registry_authorities
        }

        required_values = [("registry_urls", reg_urls)]
        if not explain:
            required_values.append(("ssh_public_key", ssh))
        missing = [name for name, value in required_values if not value]
        if missing:
            typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
            for name in missing:
                key = {
                    "ssh_public_key": "provisioning.ssh_public_key",
                    "registry_urls": "registry.urls",
                }[name]
                typer.secho(
                    f"  • {name} — set with: market config set {key} <value>",
                    err=True,
                    fg=typer.colors.RED,
                )
            raise typer.Exit(2)
        # Compile the same resource query against every selected registry
        # before retrieving candidates.
        discovery = None
        try:
            if explain:
                discovery = explain_registry_query(
                    reg_urls,
                    timeout=deadline,
                    signer=signer,
                    registry_authorities=registry_authorities,
                    resource_query=resource_query,
                    api_keys=registry_api_keys,
                )
                matches = list(discovery.listings)
            else:
                matches = query_registry_for_matches_multi(
                    reg_urls,
                    timeout=deadline,
                    signer=signer,
                    registry_authorities=registry_authorities,
                    resource_query=resource_query,
                    api_keys=registry_api_keys,
                )
        except RuntimeError as exc:
            typer.secho(f"Registry query failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3) from exc
        expiration_unix = int(time.time()) + int(expiration_seconds)
        if explain:
            assert discovery is not None

            trace = settlement_policy.explain_listings(
                matches,
                clauses=settlement_clauses,
                expiration_unix=expiration_unix,
            )
            emit_buyer_explanation(build_buyer_explanation(discovery, trace))
            return
        selected_matches = settlement_policy.select_listings(
            matches,
            clauses=settlement_clauses,
            expiration_unix=expiration_unix,
        )
        matches = []
        for match, selected in selected_matches:
            normalized = dict(match)
            normalized["_selected_settlement"] = selected
            normalized["settlement_options"] = [selected.option.model_dump(mode="json")]
            matches.append(normalized)
        preferred_mechanism = (
            matches[0]["_selected_settlement"].selection.mechanism if matches else None
        )

        if not matches:
            typer.secho(
                "No listings matched the resource and settlement constraints.",
                err=True,
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(0)
        hosted_mode = preferred_mechanism == "fiat.stripe.v1"
        chain_cfg = None
        selected_chain_name = ""
        rpc = ""
        addr_cfg: str | None = None
        addr = ""
        pk = ""
        build_escrow_terms = None
        create_escrow = None
        if not hosted_mode:
            from market_alkahest.schemas import accepted_token_address

            from .common import chain_by_name, resolve_buyer_wallet
            from .escrow_client import (
                make_buyer_payment_escrow_terms_fn,
                make_create_escrow_fn,
            )
            from .settlement_composition import alkahest_entry_from_selection

            evm_matches: list[dict[str, Any]] = []
            advertised_chains: list[str] = []
            advertised_tokens: list[str] = []
            for candidate in matches:
                selected = candidate["_selected_settlement"]
                entry = alkahest_entry_from_selection(selected)
                if entry is None:
                    continue
                advertised_chain = entry.get("chain_name")
                if not isinstance(advertised_chain, str) or not advertised_chain:
                    continue
                if not _policy.compatible(entry):
                    continue
                evm_matches.append(candidate)
                advertised_chains.append(advertised_chain)
                entry_token = accepted_token_address(entry)
                if isinstance(entry_token, str) and entry_token:
                    advertised_tokens.append(entry_token)
            matches = evm_matches
            available_chains = tuple(dict.fromkeys(advertised_chains))
            if not available_chains:
                typer.secho(
                    "No selected Alkahest option has usable accepted escrow state.",
                    err=True,
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(0)
            if len(available_chains) != 1:
                typer.secho(
                    "Selected Alkahest options span multiple chains; constrain "
                    "selection with --settlement 'mechanism=alkahest "
                    "alkahest.chain=<name>'.",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            selected_chain_name = available_chains[0]
            chain_cfg = chain_by_name(selected_chain_name)
            rpc = chain_cfg.rpc_url
            alkahest_section = settlement_policy.config.mechanism_config("alkahest")
            raw_addr_cfg = getattr(alkahest_section, "address_config_path", None)
            addr_cfg = raw_addr_cfg if isinstance(raw_addr_cfg, str) else None
            addr, pk = resolve_buyer_wallet()
            if not addr or not pk:
                typer.secho(
                    "Selected Alkahest settlement requires [Wallet] credentials.",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            if explicit_prices:
                unique_tokens = tuple(
                    dict.fromkeys(token.lower() for token in advertised_tokens)
                )
                if len(unique_tokens) != 1:
                    raise typer.BadParameter(
                        "explicit Alkahest prices require one selected asset; "
                        "constrain it with --settlement asset=<token>"
                    )

                try:
                    token_decimals = resolve_token(
                        unique_tokens[0],
                        rpc_url=rpc,
                        chain_id=chain_cfg.chain_id,
                    ).decimals
                except (TokenResolutionError, RuntimeError) as exc:
                    raise typer.BadParameter(
                        "could not resolve the selected Alkahest asset decimals"
                    ) from exc
                scale = 10 ** int(token_decimals)
                initial_price = initial_price * scale
                max_price = max_price * scale
            build_escrow_terms = make_buyer_payment_escrow_terms_fn(
                chain_name=selected_chain_name,
                addr_config_path=addr_cfg or None,
            )
            create_escrow = make_create_escrow_fn(
                private_key=pk,
                rpc_url=rpc,
                chain_name=selected_chain_name,
                addr_config_path=addr_cfg or None,
            )

        # Listed-price default: when the buyer hasn't pinned both prices
        # explicitly, both anchor on the cheapest advertised rate — open
        # there, bound there (no markup headroom; the default policy
        # never counters).
        if not explicit_prices:
            from core_buyer.cli import interactive_disposition

            initial_price, max_price = _resolve_prices_from_matches(
                matches=matches,
                console=console,
                params=policy_params_all,
                # buy bundles discovery + negotiation: this is the
                # user's first sight of what the aggregation policy
                # picked, so an interactive run confirms it.
                interactive=interactive_disposition(assume_yes),
            )
            if initial_price is None or max_price is None:
                # No advertised price, or the user declined the picks.
                raise typer.Exit(2)

        aggregation_policy = (
            aggregate_by
            or resolve_config_value(
                toml_path="aggregation.policy",
            )
            or "best_price"
        )

        config = BuyConfig.from_resolved_identity(
            identity=identity,
            registry_urls=reg_urls,
            registry_authorities=registry_authorities,
            discovery_timeout=deadline,
            registry_api_keys=registry_api_keys,
            aggregation_policy=aggregation_policy,
        )
        constraints = BuyConstraints(
            max_price=max_price,
            initial_price=initial_price,
            policy_params=policy_params_all,
        )
        provision = make_vm_provision_terms(
            duration_seconds=duration_seconds,
            start_utc=requested_start_utc,
            ssh_public_key=ssh,
        )

        def build_escrow_proposal_for_match(
            match: dict,
        ) -> EscrowProposal | SettlementSelection | None:
            selected = match.get("_selected_settlement")
            if selected is None:
                return None
            if selected.registration.config_key == "stripe":
                return selected.selection
            from .settlement_composition import alkahest_entry_from_selection

            entry = alkahest_entry_from_selection(selected)
            if entry is None:
                return None
            return escrow_proposal_from_accepted_entry(
                listing=match,
                entry=entry,
                expiration_unix=selected.selection.expiration_unix,
            )

        run_log = RunLog.start(
            command="market buy",
            profile_id=identity.profile_id,
            principal=identity.principal,
            registry_urls=reg_urls,
            policy=_policy.name,
            policy_params=policy_params_all,
            initial_price=initial_price,
            max_price=max_price,
            duration_seconds=duration_seconds,
            start_utc=requested_start_utc,
            max_matches=max_matches,
            max_rounds=max_rounds,
            **settlement_policy.public_run_metadata(),
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        header.add_row("Registries", ", ".join(reg_urls))
        header.add_row(
            "Buyer principal",
            f"{identity.principal.scheme.value}:"
            f"{identity.principal.identifier}",
        )
        if not hosted_mode:
            header.add_row("EVM wallet", addr)
        header.add_row("Opening bid / ceiling", f"{initial_price} / {max_price}")
        header.add_row("Max matches", str(max_matches))
        if resource_query is not None:
            header.add_row("Resource query", "applied")
        if not quiet:
            console.print(Panel(header, title="market buy-sync", border_style="cyan"))

        def _observe(stage: str, body: dict) -> None:
            # Append a structured event to the run log so post-mortem
            # `market logs` and (eventually) `market buy --resume` have
            # something to read. Negotiation-scoped events carry
            # listing_id (and negotiation_id once round 0 returns) so
            # consumers can group per-negotiation.
            run_log.event(stage, **body)

            # Quiet mode: drop the per-step lines; show only a single
            # "provisioning …" progress line built from the poll stream.
            if quiet:
                if stage == "settlement_submitted":
                    console.print("provisioning ", end="")
                elif stage == "settlement_poll":
                    console.print(".", end="")
                return

            # Plus a one-line console summary for the human.
            if stage == "discover":
                console.print(
                    f"[dim]discover[/dim]  {body.get('match_count', 0)} match(es)"
                )
            elif stage == "negotiation_started":
                console.print(
                    f"[dim]negotiate →[/dim] {body.get('seller_url')} ({body.get('listing_id')})"
                )
            elif stage == "negotiation_round":
                rd = body.get("round", "?")
                their = body.get("their_reply") or {}
                console.print(
                    f"[dim]  round {rd}[/dim]  → {their.get('action', '-')}"
                    f" @ {their.get('price', '-')}"
                )
            elif stage == "negotiation_completed":
                color = "green" if body.get("status") == "agreed" else "yellow"
                console.print(
                    f"[{color}]negotiate ←[/{color}] {body.get('status')} "
                    f"@ {body.get('agreed_amount', '-')}  "
                    f"({body.get('rounds', '-')} rounds)"
                )
            elif stage == "negotiation_failed":
                console.print(f"[red]negotiate ✗[/red]  {body.get('error')}")
            elif stage == "escrow_created":
                console.print(f"[green]escrow[/green]    {body.get('escrow_uid')}")
            elif stage == "settlement_submitted":
                console.print(f"[dim]settle →[/dim]  {body.get('escrow_uid')}")
            elif stage == "settlement_poll":
                st = (body.get("body") or {}).get("status")
                console.print(f"[dim]poll #{body.get('attempt')}[/dim]  status={st}")
            elif stage == "hosted_checkout_required":
                selected_action = body.get("action_policy")
                if selected_action == "open":
                    detail = "complete the action in the opened browser"
                elif selected_action == "print":
                    detail = "complete the action at the printed URL"
                else:
                    detail = "interaction is required"
                console.print(f"[cyan]Buyer action[/cyan]  {detail}")
            elif stage == "hosted_settlement_poll":
                console.print(
                    f"[dim]funding poll #{body.get('attempt')}[/dim]  "
                    f"status={body.get('status')}"
                )

        confirm_settlement_cb = None
        if not assume_yes and os.isatty(0):

            def confirm_settlement_cb(terms, listing):
                return _confirm_settlement_interactive(
                    terms=terms,
                    listing=listing,
                    console=console,
                )

        # Honor [negotiation] policies / policy_mode from buyer.toml
        # (mirrors `market negotiate` and the seller's [negotiation] knob).
        # `policies` is the explicit ordered list; `policy_mode` is the
        # legacy single-terminal key that synthesizes the default chain.
        # Without either, the buyer falls through to the default terminal
        # (RL needs torch — not installed in the lean buyer wheel).
        negotiation_chain = None
        from .common import resolve_negotiation_config

        policies, policy_mode = resolve_negotiation_config()
        if policies or policy_mode:
            from .buyer_client import load_buyer_chain

            negotiation_chain = load_buyer_chain(
                policies=policies, policy_mode=policy_mode
            )

        async def revalidate_settlement(_match, option) -> None:
            await revalidate_hosted_buyer_option(
                policy=settlement_policy,
                option=option,
                identity=identity,
                funding_selection=funding_selection,
                action_capable=action_policy is not BuyerActionPolicy.FAIL,
            )


        negotiate_hook = make_legacy_negotiate_hook(
            config=config,
            constraints=constraints,
            provision=provision,
            build_escrow_proposal=build_escrow_proposal_for_match,
            max_negotiation_rounds=max_rounds,
            derive_prices=None,
            chain=negotiation_chain,
            revalidate_settlement=revalidate_settlement,
        )
        if hosted_mode:

            def confirm_hosted(amount: int, listing: dict[str, Any]) -> bool:
                console.print(
                    f"Hosted Checkout total: [bold]{amount}[/bold] minor units "
                    f"from {listing.get('storefront_url') or listing.get('seller')}"
                )
                return typer.confirm("Proceed to hosted Checkout?", default=False)

            def print_hosted_action(url: str) -> None:
                console.print(url, markup=False)

            settle_hook = _make_hosted_settle_hook(
                config=config,
                provision=provision,
                poll_interval=poll_interval,
                total_timeout=settlement_timeout,
                sleep=time.sleep,
                action_policy=action_policy,
                open_url=webbrowser.open,
                print_url=print_hosted_action,
                confirm=(confirm_hosted if not assume_yes and os.isatty(0) else None),
                stripe_config=StripeSettlementConfig.model_validate(
                    settlement_policy.config.mechanism_config("stripe")
                ),
                funding_selection=funding_selection,
                automatic_funding=automatic_funding,
            )
        else:
            assert build_escrow_terms is not None
            assert create_escrow is not None
            settle_hook = make_legacy_settle_hook(
                config=config,
                provision=provision,
                buyer_evm_address=addr,
                build_escrow_terms=build_escrow_terms,
                create_escrow=create_escrow,
                confirm_settlement=confirm_settlement_cb,
                settlement_poll_interval=poll_interval,
                settlement_total_timeout=settlement_timeout,
                sleep=time.sleep,
            )

        try:
            result = run_buy(
                config=config,
                constraints=constraints,
                provision=provision,
                negotiate=negotiate_hook,
                settle=settle_hook,
                matches=matches,
                max_matches_to_try=max_matches,
                on_event=_observe,
            )
        except BuyerActionRequired as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.YELLOW)
            raise typer.Exit(ACTION_REQUIRED_EXIT_CODE) from exc
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Buy failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3) from exc

        run_log.end(
            result.status,
            seller_url=result.seller_url,
            negotiation_id=result.negotiation_id,
            agreed_amount=result.agreed_amount,
            escrow_uid=result.escrow_uid,
            fulfillment_uid=result.fulfillment_uid,
            reason=result.reason,
        )

        # Quiet mode: one concise block instead of the full panel. The public
        # host comes from the seller_url (the connection_details ssh_command
        # carries the seller's internal host, not its public address).
        if quiet:
            from urllib.parse import urlparse

            console.print()  # end the "provisioning …" line
            cd: dict = {}
            if result.connection_details:
                try:
                    cd = json.loads(result.connection_details)
                except (ValueError, TypeError):
                    cd = {}
            host = urlparse(result.seller_url or "").hostname or "?"
            port = (cd.get("ansible_result") or {}).get("external_ssh_port") or "?"
            user = cd.get("tenant_user") or "?"
            console.print(f"status   {result.status}")
            if result.escrow_uid:
                console.print(f"escrow   {result.escrow_uid}")
            if cd.get("vm_name"):
                console.print(f"vm       {cd['vm_name']} ({cd.get('vm_state', '?')})")
            if user != "?" and port != "?":
                console.print(f"connect  ssh -p {port} {user}@{host}")
            if result.status != "ready":
                raise typer.Exit(4)
            return

        # Render the final outcome.
        tbl = Table.grid(padding=(0, 2))
        tbl.add_column(style="bold")
        tbl.add_column()
        tbl.add_row("Status", result.status)
        for label, val in (
            ("Seller", result.seller_url),
            ("Negotiation", result.negotiation_id),
            ("Agreed price", result.agreed_amount),
            ("Escrow UID", result.escrow_uid),
            ("Fulfillment UID", result.fulfillment_uid),
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

    register_policy_verb(app, "buy", buy, _policy)
