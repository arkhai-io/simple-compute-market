"""`market <command> buy` — pure-client sequential credit buy.

Discovery and negotiation use the shared buyer orchestration. The accepted
settlement then follows its selected mechanism's stage, and the seller issues
credits only after its settlement gate and returns the credentials once
through the signed status response.

This command wires the quantity and key disposition fixed at round zero, each
stage's buy session, and credential delivery.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from typing import Any, Optional

import typer
from core_buyer import (
    BuyConfig,
    BuyConstraints,
    query_registry_for_matches_multi,
    run_buy,
)
from core_buyer.cli import (
    assume_yes_option,
    interactive_disposition,
    parse_key_value_options,
    register_policy_verb,
)
from core_buyer.deal_helpers import is_negotiation_complete
from core_buyer.orchestration import make_negotiate_hook, make_settle_hook
from core_buyer.policy_surface import configured_buyer_policy
from core_buyer.run_log import RunLog
from market_core.schemas import SettlementSelection
from market_policy.scalar_policies import selected_settlement_artifact
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arkhai_api_buying.common import (
    render_credentials,
    resolve_config_value,
    resolve_discovery_timeout,
    resolve_fresh_buyer_identity,
    resolve_indexer_urls,
    resolve_indexer_urls_for_schema,
    resolve_key_disposition,
    resolve_negotiation_config,
    resolve_prices_from_matches,
    resolve_recovery_buyer_identity,
    resolve_registry_api_keys,
    resolve_registry_authorities,
)
from arkhai_api_buying.credentials import DeliveryRunLog, end_run, record_delivery
from arkhai_api_buying.negotiate import load_buyer_chain
from arkhai_api_buying.settle import run_settle_from_log
from arkhai_api_buying.settlement_composition import BuyerSettlementComposition
from arkhai_api_buying.stages import BuyRequest, BuyRun, BuySession


def select_settlement_for_matches(
    matches: Iterable[dict[str, Any]],
    build_proposal: Callable[[dict[str, Any]], Any],
    *,
    encode_escrow_proposal: Callable[[Any], dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Choose each listing's settlement, in discovery order, until `limit` are usable.

    A listing with no proposal the buyer can make, or whose proposal resolves to
    nothing it advertises, is skipped without taking one of the `limit` tries.
    Selection stops at the limit because choosing can prompt the buyer or read
    its wallet, which no listing past the limit should cost.

    The opening and ceiling are priced from the selected settlement asset, not
    the first legacy escrow advertised beside it, so each kept listing carries
    only its selected artifact, and its proposal so that selection is not
    repeated during negotiation.
    """

    selected: list[dict[str, Any]] = []
    for match in matches:
        if len(selected) >= limit:
            break
        proposal = build_proposal(match)
        if proposal is None:
            continue
        is_selection = isinstance(proposal, SettlementSelection)
        wire = (
            {"settlement_selection": proposal.model_dump(mode="json")}
            if is_selection
            else encode_escrow_proposal(proposal)
        )
        artifact = selected_settlement_artifact(match, wire)
        if artifact is None:
            continue
        normalized = dict(match)
        normalized["_selected_buyer_proposal"] = proposal
        normalized["accepted_escrows"] = [] if is_selection else [artifact]
        if is_selection:
            normalized["settlement_options"] = [artifact]
        selected.append(normalized)
    return selected


def register(
    group: typer.Typer,
    *,
    settlement: BuyerSettlementComposition,
) -> None:
    """Register the group's `buy` command.

    Pricing flags are not defined here: the configured negotiation
    policy contributes its own parameter surface at app-assembly time
    (ARCHITECTURE.md, "Buyer negotiation policy surface") — the scalar
    policies contribute --initial-price/--max-price/--price-markup
    (per-token rates), plus the --policy-param escape hatch.
    """
    contributions = settlement.contributions
    command = contributions.command_path
    _policy = configured_buyer_policy()

    def buy(
        assume_yes: bool = assume_yes_option(
            "Skip ALL interactive prompts (price defaults + pre-settlement confirmation). Set this for scripts, CI, or non-interactive runs."
        ),
        quantity: Optional[int] = typer.Option(
            None,
            "--quantity",
            "-n",
            help="How many credits to buy. Required for fresh runs — fixed at round 0 in the provision terms and the unit count that scales per-token prices to absolute amounts. Resumed runs read the prior totals from the run-log.",
        ),
        new_key: bool = typer.Option(
            False,
            "--new-key",
            help="Issue a fresh API key for this purchase (the default disposition; the seller binds it to your marketplace principal).",
        ),
        key_id: Optional[str] = typer.Option(
            None,
            "--key-id",
            help="Top up an existing key instead of issuing a new one. The key must be bound to the authenticated marketplace principal or carry no ownership claim.",
        ),
        resource_query: Optional[str] = typer.Option(
            None,
            "--resource",
            help=f"Typed resource constraints, for example {contributions.resource_query_example!r}.",
        ),
        from_run: Optional[str] = typer.Option(
            None,
            "--from",
            help=(
                "Resume a partial buy run-id end-to-end. Continues negotiation if needed, "
                "then approves or creates the selected settlement and polls for issuance. "
                "The same run-log captures the lifecycle."
            ),
        ),
        registry_urls: Optional[str] = typer.Option(
            None,
            "--registry-urls",
            help="Comma-separated registry base URLs (default: registry.urls from config.toml). Discovery is the union across all listed registries, deduped by listing_id.",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None,
            "--discovery-timeout",
            help="Per-registry deadline in seconds (default: registry.discovery_timeout from config.toml, fallback 5).",
        ),
        expiration_seconds: int = typer.Option(
            3600,
            "--expiration",
            help="Deadline (seconds from now) the selected settlement carries. Default 1h.",
        ),
        max_matches: int = typer.Option(
            5,
            "--max-matches",
            help=(
                "How many sellers with a usable settlement option to negotiate "
                "with before giving up; listings you cannot settle with are skipped "
                "without counting."
            ),
        ),
        aggregate_by: Optional[str] = typer.Option(
            None,
            "--aggregate-by",
            help="Across-seller aggregation policy. Default: [aggregation].policy from buyer.toml, falling back to 'best_price'.",
        ),
        max_rounds: int = typer.Option(
            10, "--max-rounds", help="Per-negotiation round cap."
        ),
        poll_interval: float = typer.Option(
            5.0, "--poll-interval", help="Seconds between /settle/status polls."
        ),
        settlement_timeout: float = typer.Option(
            600.0,
            "--settlement-timeout",
            help="Max seconds to wait for issuance before giving up.",
        ),
        **policy_values: Any,
    ) -> None:
        """Buy credits end-to-end as a pure client.

        No buyer agent is started or consulted; every step is either a
        signed HTTP call to a seller, a registry query, or the selected
        mechanism's own settlement call. The issued key is shown once and kept
        in the buyer's private credential store.

        When ``--from <run_id>`` is supplied, resumes the saved deal: it
        finishes negotiation if needed, then follows the selected
        mechanism and polls for issued credentials.
        """
        console = Console()
        options, policy_values = settlement.split_options(policy_values, "buy")
        policy_params_all: dict[str, Any] = {
            k: v for k, v in policy_values.items() if k != "policy_param"
        }
        policy_params_all.update(
            parse_key_value_options(
                policy_values.get("policy_param") or [], option_name="--policy-param"
            )
        )
        initial_price: Optional[float] = policy_params_all.get("initial_price")
        max_price: Optional[float] = policy_params_all.get("max_price")
        identity = (
            resolve_recovery_buyer_identity(from_run)
            if from_run
            else resolve_fresh_buyer_identity()
        )
        signer = identity.signer
        principal = identity.principal
        buyer_settlement = settlement.resolve_policy(identity=identity)
        config_keys = {
            registration.mechanism_id: registration.config_key
            for registration in buyer_settlement.registry.registrations
        }
        sessions: dict[str, BuySession] = {}
        enabled: list[BuySession] = []
        for mechanism, stage in settlement.stages.items():
            section = buyer_settlement.config.mechanism_config(config_keys[mechanism])
            is_enabled = bool(section is not None and getattr(section, "enabled", False))
            sessions[mechanism] = stage.open_buy(BuyRequest(
                identity=identity,
                settlement=buyer_settlement,
                policy=_policy,
                enabled=is_enabled,
                options=options,
                assume_yes=assume_yes,
                console=console,
            ))
            if is_enabled:
                enabled.append(sessions[mechanism])
        if from_run:
            if not is_negotiation_complete(from_run, signer=signer):
                typer.secho(
                    f"Run-log has no agreed negotiation. Resume the round loop with `{command} negotiate --from <run-id>` first, then settle.",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            run_settle_from_log(
                settlement,
                identity=identity,
                run_id=from_run,
                options=options,
                poll_interval=poll_interval,
                settlement_timeout=settlement_timeout,
                console=console,
            )
            return
        # A resumed run completes under its accepted mechanism whatever is
        # enabled now; enablement gates only the selection of a fresh deal.
        if not enabled:
            raise typer.BadParameter("no buyer settlement mechanism is enabled")
        if quantity is None or quantity < 1:
            typer.secho(
                f"Fresh `{command} buy` runs require --quantity >= 1 (how many credits to buy).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        key_mode, resolved_key_id = resolve_key_disposition(
            new_key=new_key, key_id=key_id
        )
        explicit_prices = initial_price is not None and max_price is not None
        if not explicit_prices and (initial_price is not None) != (
            max_price is not None
        ):
            typer.secho(
                "Pass both --initial-price and --max-price, or neither (in which case prices are derived from the advertised rate).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        deadline = resolve_discovery_timeout(override=discovery_timeout)
        candidate_urls = resolve_indexer_urls(override=registry_urls)
        registry_authorities = resolve_registry_authorities(candidate_urls)
        reg_urls = resolve_indexer_urls_for_schema(
            contributions.schema_id,
            signer=signer,
            registry_authorities=registry_authorities,
            override=registry_urls,
            timeout=deadline,
        )
        registry_authorities = {url: registry_authorities[url] for url in reg_urls}
        all_registry_api_keys = resolve_registry_api_keys()
        registry_api_keys = {
            url: all_registry_api_keys[url]
            for url in reg_urls
            if url in all_registry_api_keys
        }
        for session in sessions.values():
            session.prepare()
        missing: list[tuple[str, str]] = (
            [] if reg_urls else [("registry_urls", "registry.urls")]
        )
        if not any(session.available for session in enabled):
            for session in enabled:
                missing.extend(session.missing())
        if missing:
            typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
            for name, key in missing:
                typer.secho(
                    f"  • {name} — set with: market config set {key} <value>",
                    err=True,
                    fg=typer.colors.RED,
                )
            raise typer.Exit(2)
        if explicit_prices:
            for session in sessions.values():
                initial_price, max_price = session.scale_explicit_prices(
                    initial_price, max_price
                )
        try:
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
            raise typer.Exit(3)
        if not matches:
            typer.secho(
                "No listings matched the resource constraints.",
                err=True,
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(0)
        expiration_unix = int(time.time()) + int(expiration_seconds)

        def build_proposal_for_match(match: dict) -> Any | None:
            if "_selected_buyer_proposal" in match:
                return match["_selected_buyer_proposal"]
            return settlement.select_proposal(
                buyer_settlement, match, sessions, expiration_unix=expiration_unix,
            )

        escrow = settlement.escrow_codec
        matches = select_settlement_for_matches(
            matches,
            build_proposal_for_match,
            encode_escrow_proposal=escrow.encode_proposal,
            limit=max_matches,
        )

        if not explicit_prices:
            initial_price, max_price = resolve_prices_from_matches(
                matches=matches,
                console=console,
                params=policy_params_all,
                interactive=interactive_disposition(assume_yes),
            )
            if initial_price is None or max_price is None:
                raise typer.Exit(2)
        aggregation_policy = (
            aggregate_by or resolve_config_value(toml_path="aggregation.policy") or None
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
        provision = contributions.provision_terms.purchase(
            quantity=int(quantity), key_mode=key_mode, key_id=resolved_key_id
        )
        run_fields: dict[str, Any] = {}
        for session in sessions.values():
            run_fields.update(session.run_fields())
        run_log = DeliveryRunLog.of(RunLog.start(
            profile_id=identity.profile_id,
            principal=identity.principal,
            command=f"{command} buy",
            registry_urls=reg_urls,
            policy=_policy.name,
            policy_params=policy_params_all,
            initial_price=initial_price,
            max_price=max_price,
            quantity=quantity,
            key_mode=key_mode,
            key_id=resolved_key_id,
            max_matches=max_matches,
            max_rounds=max_rounds,
            **run_fields,
        ))
        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        header.add_row("Registries", ", ".join(reg_urls))
        header.add_row(
            "Marketplace principal", f"{principal.scheme.value}:{principal.identifier}"
        )
        for session in sessions.values():
            for label, value in session.header_rows():
                header.add_row(label, value)
        header.add_row("Quantity", str(quantity))
        header.add_row(
            "Key", key_mode + (f" ({resolved_key_id})" if resolved_key_id else "")
        )
        header.add_row(
            "Opening bid / ceiling (per token)", f"{initial_price} / {max_price}"
        )
        header.add_row("Max matches", str(max_matches))
        if resource_query is not None:
            header.add_row("Resource query", "applied")
        console.print(Panel(header, title=f"{command} buy", border_style="cyan"))

        def _observe(stage: str, body: dict) -> None:
            run_log.event(stage, **body)
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
                proposal = their.get("proposal") or {}
                amount = (proposal.get("fields") or {}).get("amount", "-")
                console.print(
                    f"[dim]  round {rd}[/dim]  → {their.get('action', '-')} @ {amount}"
                )
            elif stage == "negotiation_completed":
                color = "green" if body.get("status") == "agreed" else "yellow"
                console.print(
                    f"[{color}]negotiate ←[/{color}] {body.get('status')} @ {body.get('agreed_amount', '-')}  ({body.get('rounds', '-')} rounds)"
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

        policies, policy_mode = resolve_negotiation_config()
        negotiation_chain = load_buyer_chain(
            settlement,
            policies=policies,
            policy_mode=policy_mode,
        )
        negotiate_hook = make_negotiate_hook(
            config=config,
            constraints=constraints,
            provision=provision,
            unit_count=float(quantity),
            build_escrow_proposal=build_proposal_for_match,
            encode_escrow_proposal=escrow.encode_proposal,
            max_negotiation_rounds=max_rounds,
            derive_prices=None,
            chain=negotiation_chain,
            decode_provision_terms=contributions.provision_terms.model_validate,
            decode_escrow_proposal=escrow.decode_proposal,
            decode_escrow_terms=escrow.decode_terms,
            validate_acceptance=settlement.validate_acceptance,
        )
        run = BuyRun(
            config=config,
            quantity=int(quantity),
            poll_interval=poll_interval,
            settlement_timeout=settlement_timeout,
            interactive=not assume_yes and os.isatty(0),
        )

        def invoke_stage(stage, negotiation, on_event):
            return sessions[stage.mechanism_id].settle(negotiation, on_event, run)

        settle_hook = make_settle_hook(stages=settlement.stages, invoke=invoke_stage)

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
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Buy failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)
        delivery = record_delivery(
            run_log, result.tenant_credentials, settlement.credential_store
        )
        end_run(
            run_log,
            delivery,
            result.status,
            seller_url=result.seller_url,
            negotiation_id=result.negotiation_id,
            agreed_amount=result.agreed_amount,
            escrow_uid=result.escrow_uid,
            settlement_ref=result.settlement_ref,
            fulfillment_uid=result.fulfillment_uid,
            reason=result.reason,
        )
        tbl = Table.grid(padding=(0, 2))
        tbl.add_column(style="bold")
        tbl.add_column()
        tbl.add_row("Status", result.status)
        for label, val in (
            ("Seller", result.seller_url),
            ("Negotiation", result.negotiation_id),
            ("Agreed amount (total)", result.agreed_amount),
            ("Escrow UID", result.escrow_uid),
            ("Settlement ref", result.settlement_ref),
            ("Fulfillment UID", result.fulfillment_uid),
            ("Reason", result.reason),
        ):
            if val:
                tbl.add_row(label, str(val))
        border = {
            "ready": "green",
            "failed": "red",
            "timeout": "red",
            "exited": "yellow",
            "no_matches": "yellow",
        }.get(result.status, "white")
        console.print(Panel(tbl, title="Buy complete", border_style=border))
        if delivery is not None:
            render_credentials(
                console, delivery, run_id=run_log.run_id, command_path=command
            )
        if result.status != "ready":
            raise typer.Exit(4)

    register_policy_verb(group, "buy", settlement.add_options(buy, "buy"), _policy)
