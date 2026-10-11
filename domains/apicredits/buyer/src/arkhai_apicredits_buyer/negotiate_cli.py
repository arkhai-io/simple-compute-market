"""`market credits negotiate` — buyer-as-client sync negotiation, one deal.

Thin wrapper around ``core_buyer.negotiation_client``. Prices are
per-token rates; the requested ``--quantity`` is the unit count that
scales them to the absolute amounts the negotiation runs on. The key
disposition (``--new-key`` / ``--key-id``) is fixed at round 0 inside
the provision terms, exactly like the VM lease duration.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import arkhai_apicredits.negotiation.buyer_policies as buyer_policies  # registers answer_key_challenge
from .buyer_client import ResumeState, load_buyer_chain, negotiate_with_seller
from core_buyer.cli import assume_yes_option, parse_key_value_options, register_policy_verb
from core_buyer.deal_helpers import load_negotiation_resume_point, settlement_acceptance_fields
from core_buyer.orchestration import make_publisher_trust_resolver
from core_buyer.orchestrator import BuyConfig, fetch_listing_dict
from core_buyer.policy_surface import configured_buyer_policy
from market_identity import TrustedIdentitySet
from market_core.schemas import SettlementSelection
from core_buyer.run_log import RunLog
from arkhai_apicredits.negotiation import (
    make_api_credits_provision_terms,
    provision_key_id,
    provision_key_mode,
    provision_quantity,
)

from .cli_helpers import resolve_prices_from_matches
from .settlement_composition import BUYER_STAGES, resolve_buyer_settlement_policy
from .common import (
    APICREDITS_SCHEMA_ID,
    make_run_publisher_principals_refresh,
    resolve_discovery_timeout,
    resolve_fresh_buyer_identity,
    resolve_indexer_urls,
    resolve_indexer_urls_for_schema,
    resolve_key_disposition,
    resolve_negotiation_config,
    resolve_recovery_buyer_identity,
    resolve_registry_api_keys,
    resolve_registry_authorities,
)


def register(credits_app: typer.Typer) -> None:
    """Register `market credits negotiate`.

    Pricing flags come from the configured negotiation policy
    (ARCHITECTURE.md, "Buyer negotiation policy surface"), injected at
    app assembly — the scalar policies contribute --initial-price/
    --max-price/--price-markup, plus the --policy-param escape hatch.
    """
    _policy = configured_buyer_policy()

    def negotiate(  # registered below after policy-param injection
        seller_url: Optional[str] = typer.Option(
            None,
            "--seller",
            "-s",
            help="Seller storefront base URL. Optional — resolved from the "
            "registry given --listing-id; resumed runs (--from) "
            "read it from the run-log. Pass explicitly to override.",
        ),
        listing_id: Optional[str] = typer.Option(
            None,
            "--listing-id",
            help="The seller's listing_id. Required for fresh runs; "
            "resumed runs (--from) read it from the run-log.",
        ),
        quantity: Optional[int] = typer.Option(
            None,
            "--quantity",
            "-n",
            help="How many credits to buy. Required for fresh "
            "runs — fixed at round 0 in the provision terms and the "
            "unit count that scales per-token prices to absolute "
            "amounts. Resumed runs read the prior totals from the run-log.",
        ),
        new_key: bool = typer.Option(
            False,
            "--new-key",
            help="Issue a fresh API key for this purchase (the default "
            "disposition; the seller binds it to your marketplace principal).",
        ),
        key_id: Optional[str] = typer.Option(
            None,
            "--key-id",
            help="Top up an existing key instead of issuing a new one. "
            "The key must be bound to the authenticated marketplace principal "
            "or carry no ownership claim.",
        ),
        registry_urls: Optional[str] = typer.Option(
            None,
            "--registry-urls",
            help="Comma-separated registry base URLs (default: "
            "registry.urls from config.toml).",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None,
            "--discovery-timeout",
            help="Per-registry deadline in seconds (default: "
            "registry.discovery_timeout from config.toml, fallback 5).",
        ),
        assume_yes: bool = assume_yes_option(
            "Skip interactive confirmations on auto-derived prices.",
        ),
        max_rounds: int = typer.Option(
            10,
            "--max-rounds",
            help="Walk away after this many buyer-initiated counters.",
        ),
        from_run: Optional[str] = typer.Option(
            None,
            "--from",
            help="Resume the round loop of a prior run (by run-id). Skips "
            "/negotiate/new; replays the seller's last counter into "
            "the strategy and continues.",
        ),
        evm_address: Optional[str] = typer.Option(
            None,
            "--evm-address",
            help="EVM address used only for chain selection and balance checks.",
        ),
        evm_private_key: Optional[str] = typer.Option(
            None,
            "--evm-private-key",
            help="Optional EVM key used only to derive the chain address.",
        ),
        token_contract: Optional[str] = typer.Option(
            None,
            "--token-contract",
            help="Optional ERC-20 accepted-escrow filter. Omit to use the "
            "token/escrow shape selected from the listing.",
        ),
        token_decimals: Optional[float] = typer.Option(
            None,
            "--token-decimals",
            help="ERC-20 token decimals override for scaling price flags. "
            "Only needed when decimals cannot be resolved on chain.",
        ),
        chain_name: Optional[str] = typer.Option(
            None,
            "--chain",
            help="Which [chains.<name>] entry to negotiate against. When "
            "omitted the buyer prompts; required when --yes is set "
            "and the listing accepts more than one chain you have configured.",
        ),
        **policy_values: Any,
    ) -> None:
        """Drive a synchronous token negotiation, round-by-round.

        Each round is a signed HTTP POST to the seller. The seller's
        policy decides counter/accept/exit and returns the decision
        inline. The buyer's policy decides locally in this process
        (default: listed_price — pay what's published).
        """
        console = Console()

        policy_params_all: dict[str, Any] = {
            k: v for k, v in policy_values.items() if k != "policy_param"
        }
        policy_params_all.update(
            parse_key_value_options(
                policy_values.get("policy_param") or [],
                option_name="--policy-param",
            )
        )
        initial_price: Optional[float] = policy_params_all.get("initial_price")
        max_price: Optional[float] = policy_params_all.get("max_price")

        # Capture which prices the user passed explicitly — auto-derived
        # values (from the listing's advertised rate) are already in
        # base units and must not be scaled again below.
        _initial_explicit = initial_price is not None
        _max_explicit = max_price is not None

        identity = (
            resolve_recovery_buyer_identity(from_run)
            if from_run
            else resolve_fresh_buyer_identity()
        )
        signer = identity.signer
        principal = identity.principal

        key_mode, resolved_key_id = resolve_key_disposition(
            new_key=new_key,
            key_id=key_id,
        )

        resume_state = None
        resume_point = None
        if from_run:
            resume_point = load_negotiation_resume_point(
                from_run,
                signer=signer,
                refresh_publisher_principals=make_run_publisher_principals_refresh(
                    from_run,
                    signer=signer,
                ),
            )
            seller_url = seller_url or resume_point.seller_url
            listing_id = listing_id or resume_point.listing_id
            if initial_price is not None or max_price is not None:
                raise typer.BadParameter(
                    "price options apply only to fresh negotiation; resume uses "
                    "the persisted scaled opening and ceiling"
                )
            initial_price = resume_point.initial_price
            max_price = resume_point.max_price
            quantity = provision_quantity(resume_point.accepted_provision_terms)
            if quantity is None or quantity < 1:
                raise typer.BadParameter("run has no recorded credit quantity")
            key_mode = provision_key_mode(resume_point.accepted_provision_terms)
            resolved_key_id = provision_key_id(resume_point.accepted_provision_terms)
            resume_state = ResumeState(
                negotiation_id=resume_point.negotiation_id,
                transcript=resume_point.transcript,
                last_seller_proposal=resume_point.last_seller_proposal,
                rounds_completed=resume_point.rounds_completed,
                accepted_provision_terms=resume_point.accepted_provision_terms,
                accepted_escrow_proposal=resume_point.accepted_escrow_proposal,
                settlement_selection=resume_point.settlement_selection,
                settlement_plan=resume_point.settlement_plan,
                accepted_escrow_terms=resume_point.accepted_escrow_terms,
            )
            if resume_point.settlement_selection is None:
                raise typer.BadParameter("run has no recorded settlement selection")
            mechanism = SettlementSelection.model_validate(
                resume_point.settlement_selection,
            ).mechanism
            if mechanism not in BUYER_STAGES:
                raise typer.BadParameter("unsupported recorded API-credit settlement mechanism")

        if resume_state is None:
            deadline = resolve_discovery_timeout(override=discovery_timeout)
            candidate_urls = resolve_indexer_urls(override=registry_urls)
            registry_authorities = resolve_registry_authorities(candidate_urls)
            reg_urls = resolve_indexer_urls_for_schema(
                APICREDITS_SCHEMA_ID,
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
        else:
            deadline = resolve_discovery_timeout(override=discovery_timeout)
            reg_urls = [resume_point.source_registry_url]
            registry_authorities = resolve_registry_authorities(reg_urls)
            registry_api_keys = {
                url: key for url, key in resolve_registry_api_keys().items()
                if url in registry_authorities
            }

        # Fetch the listing — needed for both --seller auto-resolution
        # and picking an accepted_escrows entry. Skipped in resume mode.
        listing_dict: Optional[dict] = None
        if listing_id and resume_state is None:
            last_error: RuntimeError | None = None
            for registry_url in reg_urls:
                try:
                    listing_dict = fetch_listing_dict(
                        registry_url,
                        listing_id,
                        timeout=deadline,
                        signer=signer,
                        registry_authority=registry_authorities[registry_url],
                        api_key=registry_api_keys.get(registry_url),
                    )
                except RuntimeError as exc:
                    last_error = exc
                    continue
                if listing_dict is not None:
                    listing_dict["source_registry_url"] = registry_url
                    listing_dict["source_registry_authority"] = registry_authorities[
                        registry_url
                    ].authority
                    break
            if listing_dict is None and last_error is not None:
                typer.secho(
                    f"Could not fetch listing {listing_id}: {last_error}",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            if not listing_dict:
                typer.secho(
                    f"No listing {listing_id!r} in any of {len(reg_urls)} registries.",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            if not seller_url:
                seller_url = listing_dict.get("storefront_url") or listing_dict.get(
                    "seller"
                )
                if not seller_url:
                    typer.secho(
                        f"Listing {listing_id} has no storefront URL; pass --seller explicitly.",
                        err=True,
                        fg=typer.colors.RED,
                    )
                    raise typer.Exit(2)

        if not seller_url or not listing_id:
            typer.secho(
                "Missing required negotiation inputs. For a fresh run pass "
                "--listing-id (and optionally --seller); for a resume pass --from <run-id>.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        if resume_state is None and (quantity is None or quantity < 1):
            typer.secho(
                "Fresh runs require --quantity >= 1 (how many credits to buy).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        selected_settlement = None
        selected_stage = None
        picked_entry = None
        if listing_dict is not None:
            try:
                settlement_policy = resolve_buyer_settlement_policy(identity=identity)
                selected_settlement = settlement_policy.select(
                    listing_dict, expiration_unix=int(time.time()) + 3600,
                )
                if selected_settlement is None:
                    raise ValueError(
                        f"listing {listing_id!r} has no installed, enabled, compatible "
                        "settlement option"
                    )
                selected_stage = BUYER_STAGES[selected_settlement.selection.mechanism]
                selected_settlement = selected_stage.prepare_selection(
                    selected_settlement, listing=listing_dict,
                    settlement_policy=settlement_policy, policy=_policy,
                    chain_name=chain_name, token_contract=token_contract,
                    evm_address=evm_address, evm_private_key=evm_private_key,
                    assume_yes=assume_yes, console=console,
                )
                picked_entry = selected_stage.accepted_entry(selected_settlement)
                initial_price, max_price = selected_stage.negotiation_prices(
                    selected_settlement, initial_price=initial_price, max_price=max_price,
                    initial_explicit=_initial_explicit, max_explicit=_max_explicit,
                    token_decimals=token_decimals,
                )
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc

            if initial_price is None or max_price is None:
                pricing_listing = dict(listing_dict)
                pricing_listing["settlement_options"] = [
                    selected_settlement.option.model_dump(mode="json"),
                ]
                pricing_listing["accepted_escrows"] = [picked_entry] if picked_entry else []
                pricing_params = dict(policy_params_all)
                if _initial_explicit:
                    pricing_params["initial_price"] = initial_price
                if _max_explicit:
                    pricing_params["max_price"] = max_price
                initial_price, max_price = resolve_prices_from_matches(
                    matches=[pricing_listing], console=console, params=pricing_params,
                )
                if initial_price is None or max_price is None:
                    raise typer.Exit(2)

        expected_seller_principals = (
            resume_point.publisher_principals
            if resume_point is not None
            else TrustedIdentitySet.model_validate_json(
                json.dumps((listing_dict or {}).get("publisher_principals")),
            )
        )
        publisher_id = (
            resume_point.publisher_id
            if resume_point is not None
            else (listing_dict or {}).get("publisher_id")
        )
        source_registry_url = (
            resume_point.source_registry_url
            if resume_point is not None
            else (listing_dict or {}).get("source_registry_url")
        )
        source_registry_authority = (
            resume_point.source_registry_authority
            if resume_point is not None
            else (listing_dict or {}).get("source_registry_authority")
        )
        if (
            publisher_id is None
            or not source_registry_url
            or not source_registry_authority
            or not seller_url
            or not listing_id
        ):
            raise RuntimeError(
                "negotiation requires exact publisher and registry source bindings"
            )
        trust_listing = {
            "listing_id": listing_id,
            "publisher_id": publisher_id,
            "publisher_principals": expected_seller_principals.model_dump(mode="json"),
            "storefront_url": seller_url,
            "source_registry_url": source_registry_url,
            "source_registry_authority": source_registry_authority,
        }
        run_log = RunLog.start(
            profile_id=identity.profile_id,
            principal=identity.principal,
            command="market credits negotiate",
            seller_url=seller_url,
            listing_id=listing_id,
            publisher_principals=expected_seller_principals.model_dump(mode="json"),
            publisher_id=publisher_id,
            source_registry_url=source_registry_url,
            source_registry_authority=source_registry_authority,
            policy=_policy.name,
            policy_params=policy_params_all,
            initial_price=initial_price,
            max_price=max_price,
            max_rounds=max_rounds,
            quantity=quantity,
            key_mode=key_mode,
            key_id=resolved_key_id,
            token_contract=token_contract,
            token_decimals=token_decimals,
            resumed_from=from_run,
            chain_name=(picked_entry.get("chain_name") if picked_entry else None),
        )
        resolve_seller_principals = make_publisher_trust_resolver(
            config=BuyConfig.from_resolved_identity(
                identity=identity,
                registry_urls=reg_urls,
                registry_authorities=registry_authorities,
                discovery_timeout=deadline,
                registry_api_keys=registry_api_keys,
            ),
            listing=trust_listing,
            on_update=lambda event, fields: run_log.event(event, **fields),
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        if from_run:
            header.add_row("Resumed from", from_run)
        header.add_row("Seller", seller_url)
        header.add_row("Listing", listing_id)
        if quantity is not None:
            header.add_row("Quantity", str(quantity))
        header.add_row(
            "Key", key_mode + (f" ({resolved_key_id})" if resolved_key_id else "")
        )
        if initial_price is not None:
            header.add_row("Opening bid (per token)", str(initial_price))
        header.add_row("Ceiling (per token)", str(max_price))
        header.add_row("Max rounds", str(max_rounds))
        console.print(
            Panel(header, title="market credits negotiate", border_style="cyan")
        )

        round_table = Table(title="Rounds", show_lines=False)
        round_table.add_column("#")
        round_table.add_column("Our action")
        round_table.add_column("Seller action")
        round_table.add_column("Seller amount")

        def _observe(round_idx: int, our_msg: dict, reply: dict) -> None:
            run_log.event(
                "negotiation_round",
                round=round_idx,
                our_message=our_msg,
                their_reply=reply,
            )
            their_proposal = reply.get("proposal") or {}
            their_amount = (their_proposal.get("fields") or {}).get("amount", "-")
            round_table.add_row(
                str(round_idx),
                str(our_msg.get("action", "propose")),
                str(reply.get("action", "-")),
                str(their_amount),
            )

        provision_terms = None
        escrow_proposal = None
        settlement_selection = None
        if resume_state is None:
            assert quantity is not None  # gated above
            assert selected_settlement is not None
            assert selected_stage is not None
            provision_terms = make_api_credits_provision_terms(
                quantity=int(quantity),
                key_mode=key_mode,
                key_id=resolved_key_id,
            )
            proposal = selected_stage.proposal(listing_dict or {}, selected_settlement)
            if isinstance(proposal, SettlementSelection):
                settlement_selection = proposal
            else:
                escrow_proposal = proposal

        # Honor optional [negotiation] policies / policy_mode overrides
        # in buyer.toml; a resume continues under the policy that opened
        # the negotiation. Either way the chain is loaded with the
        # API-credits default guards so answer_key_challenge always rides.
        if resume_state is not None:
            policies, policy_mode = None, resume_point.policy
        else:
            policies, policy_mode = resolve_negotiation_config()
        chain = load_buyer_chain(
            policies=policies,
            policy_mode=policy_mode,
            default_guards=buyer_policies.APICREDITS_BUYER_GUARDS,
        )

        negotiation_policy_params = dict(policy_params_all)
        if selected_settlement is not None:
            negotiation_policy_params["_selected_settlement_option"] = (
                selected_settlement.option.model_dump(mode="json")
            )

        # Fresh core rounds scale per-credit bounds; resumed core rounds expect
        # absolute bounds because their opening proposal is already persisted.
        resume_units = float(quantity) if resume_state is not None else 1.0
        try:
            outcome = negotiate_with_seller(
                seller_url=seller_url,
                principal=principal,
                signer=signer,
                listing_id=listing_id,
                initial_price=(initial_price or 0) * resume_units,
                max_price=max_price * resume_units,
                unit_count=(float(quantity) if resume_state is None else None),
                provision_terms=provision_terms,
                escrow_proposal=escrow_proposal,
                settlement_selection=settlement_selection,
                max_rounds=max_rounds,
                on_round=_observe,
                resume=resume_state,
                chain=chain,
                policy_params=negotiation_policy_params,
                resolve_seller_principals=resolve_seller_principals,
            )
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Negotiation failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        run_log.end(
            outcome.status,
            negotiation_id=outcome.negotiation_id,
            agreed_amount=outcome.agreed_amount,
            rounds=outcome.rounds,
            reason=outcome.reason,
            **settlement_acceptance_fields(
                negotiation_id=outcome.negotiation_id or "",
                selection=outcome.settlement_selection,
                plan=outcome.settlement_plan,
            ),
            agreement_bytes=outcome.agreement_bytes,
            settlement_data=outcome.settlement_data,
            accepted_escrow_proposal=(
                outcome.accepted_escrow_proposal.model_dump()
                if outcome.accepted_escrow_proposal is not None
                else None
            ),
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

        console.print(round_table)

        result_table = Table.grid(padding=(0, 2))
        result_table.add_column(style="bold")
        result_table.add_column()
        result_table.add_row("Status", outcome.status)
        if outcome.negotiation_id:
            result_table.add_row("Negotiation", outcome.negotiation_id)
        if outcome.agreed_amount is not None:
            result_table.add_row("Agreed amount (total)", str(outcome.agreed_amount))
        if outcome.reason:
            result_table.add_row("Reason", outcome.reason)
        result_table.add_row("Rounds", str(outcome.rounds))

        border = "green" if outcome.status == "agreed" else "yellow"
        console.print(Panel(result_table, title="Outcome", border_style=border))

        if outcome.status != "agreed":
            raise typer.Exit(4)

    register_policy_verb(credits_app, "negotiate", negotiate, _policy)
