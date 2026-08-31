"""`market credits buy` — pure-client sequential credit buy.

Drives the deal end-to-end from the CLI process:

    discover (registry, api-credits schema) →
    negotiate each match (sync HTTP rounds, quantity × per-token rate) →
    pick agreed match →
    create escrow on-chain (alkahest-py in-process) →
    POST /settle/{uid} on seller →
    poll /settle/{uid}/status until ready/failed →
    deliver the issued credentials to the run-log.

The orchestration stages are core (``core_buyer.orchestration``); this
command wires the API-credits instantiation: the quantity unit count,
the key disposition fixed at round 0, the durationless escrow terms,
and the once-only credential delivery.
"""

from __future__ import annotations

import os
import webbrowser
import time
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import domains.apicredits.negotiation.buyer_policies as buyer_policies  # registers answer_key_challenge
from core_buyer import (
    BuyConfig,
    BuyConstraints,
    query_registry_for_matches_multi,
    run_buy,
    make_hosted_settle_hook,
)
from core_buyer.action_policy import resolve_buyer_action_policy
from core_buyer.deal_helpers import is_negotiation_complete
from .buyer_client import load_buyer_chain
from core_buyer.orchestration import make_negotiate_hook, make_settle_hook
from core_buyer.run_log import RunLog
from domains.apicredits.negotiation import (
    ApiCreditsProvisionTerms,
    make_api_credits_provision_terms,
)
from market_alkahest.proposals import escrow_proposal_from_accepted_entry
from market_alkahest.schemas import EscrowProposal, EscrowTerms
from market_hosted_settlement import (
    MECHANISM as HOSTED_MECHANISM,
    FundingMode,
    FundingProfile,
    FundingSelection,
)

from .cli_helpers import resolve_prices_from_matches
from .common import resolve_config_value
from .hosted_authorization import prepare_hosted_funding_authorization
from .settlement_composition import resolve_buyer_settlement_policy
from .settle_cli import render_credentials, run_settle_from_log


def _confirm_settlement_interactive(
    *,
    terms,
    listing: dict,
    quantity: int,
    console: Console,
) -> bool:
    """Prompt the buyer to approve settlement at the negotiated total.

    Shown after negotiation agrees but BEFORE create_escrow runs — i.e.,
    no on-chain transaction has been emitted and the seller's /settle
    endpoint hasn't been touched yet. Declining here is a clean exit.
    """
    per_token = terms.agreed_amount / quantity if quantity else 0
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Seller", str(terms.seller_url))
    table.add_row("Listing", str(terms.listing_id))
    table.add_row("Negotiation", str(terms.negotiation_id))
    table.add_row("Quantity", str(quantity))
    table.add_row("Per-token rate", f"{per_token:.6g} (raw token units)")
    table.add_row("Total payment", f"{terms.agreed_amount} (raw token units)")
    console.print(Panel(table, title="Confirm settlement", border_style="yellow"))
    try:
        return typer.confirm(
            "Proceed to settlement (escrow + /settle + poll)?", default=True
        )
    except typer.Abort:
        return False


def register(credits_app: typer.Typer) -> None:
    """Register `market credits buy`.

    Pricing flags are not defined here: the configured negotiation
    policy contributes its own parameter surface at app-assembly time
    (ARCHITECTURE.md, "Buyer negotiation policy surface") — the scalar
    policies contribute --initial-price/--max-price/--price-markup
    (per-token rates), plus the --policy-param escape hatch.
    """

    from core_buyer.cli import (
        assume_yes_option,
        parse_key_value_options,
        register_policy_verb,
    )
    from core_buyer.policy_surface import configured_buyer_policy

    _policy = configured_buyer_policy()

    def buy(  # registered below after policy-param injection
        assume_yes: bool = assume_yes_option(
            "Skip ALL interactive prompts (price defaults + "
            "pre-settlement confirmation). Set this for scripts, CI, "
            "or non-interactive runs.",
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
        resource_query: Optional[str] = typer.Option(
            None,
            "--resource",
            help="Typed resource constraints, for example "
            "'service_name=weather token in [0xabc,0xdef]'.",
        ),
        from_run: Optional[str] = typer.Option(
            None,
            "--from",
            help="Resume a partial buy run-id end-to-end. Continues "
            "negotiation if it stopped mid-stream, then drives "
            "escrow.create + /settle + poll. The same run-log is "
            "appended to, so it captures the full lifecycle.",
        ),
        registry_urls: Optional[str] = typer.Option(
            None,
            "--registry-urls",
            help="Comma-separated registry base URLs (default: "
            "registry.urls from config.toml). Discovery is the "
            "union across all listed registries, deduped by listing_id.",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None,
            "--discovery-timeout",
            help="Per-registry deadline in seconds (default: "
            "registry.discovery_timeout from config.toml, fallback 5).",
        ),
        token_contract: Optional[str] = typer.Option(
            None,
            "--token-contract",
            help="Optional filter: only consider listings whose accepted "
            "escrow uses this ERC-20. Required when passing explicit "
            "--initial-price/--max-price (decimals scaling).",
        ),
        token_decimals: Optional[int] = typer.Option(
            None,
            "--token-decimals",
            help="ERC-20 token decimals override. When omitted, decimals "
            "are resolved on chain via the token contract's "
            "decimals() view.",
        ),
        chain_name: Optional[str] = typer.Option(
            None,
            "--chain",
            help="Pick which configured [chains.<name>] entry to operate on. "
            "Required when --yes is set and the buyer has more than one "
            "chain configured; otherwise the buyer prompts.",
        ),
        expiration_seconds: int = typer.Option(
            3600,
            "--expiration",
            help="Escrow deadline (seconds from now) for the "
            "reclaim_expired escape hatch. Default 1h.",
        ),
        funding_profile: Optional[str] = typer.Option(
            None,
            "--funding-profile",
            help="Use an exact hosted profile: card.v1, us_bank_transfer.v1, "
            "or us_ach_debit.v1. Omit to preserve Alkahest when both are enabled.",
        ),
        funding_mode: str = typer.Option(
            "interactive",
            "--funding-mode",
            help="Hosted funding mode: interactive or saved_instrument.",
        ),
        instrument_ref: Optional[str] = typer.Option(
            None,
            "--instrument-ref",
            help="Opaque hosted instrument reference for saved_instrument mode.",
        ),
        action: Optional[str] = typer.Option(
            None,
            "--action",
            help="Hosted transient-action policy: open, print, or fail.",
        ),
        automatic_funding: bool = typer.Option(
            False,
            "--automatic-funding",
            help="Evaluate the bounded local off-session policy for this purchase.",
        ),
        max_matches: int = typer.Option(
            5,
            "--max-matches",
            help="How many matching seller listings to try before giving up.",
        ),
        aggregate_by: Optional[str] = typer.Option(
            None,
            "--aggregate-by",
            help="Across-seller aggregation policy. Default: "
            "[aggregation].policy from buyer.toml, falling "
            "back to 'best_price'.",
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
            help="Max seconds to wait for issuance before giving up.",
        ),
        evm_address: Optional[str] = typer.Option(
            None,
            "--evm-address",
            help="EVM address required for the selected Alkahest effect.",
        ),
        evm_private_key: Optional[str] = typer.Option(
            None,
            "--evm-private-key",
            help="EVM private key required only to create the Alkahest escrow.",
        ),
        **policy_values: Any,
    ) -> None:
        """Buy API credits end-to-end as a pure HTTP/web3 client.

        No buyer agent is started or consulted; every step is either a
        signed HTTP call to a seller, a registry query, or a direct
        on-chain call. The issued credentials are shown once and saved
        to the run-log.

        When ``--from <run_id>`` is supplied, picks up wherever the
        prior run left off: finishes the negotiation if it stopped
        mid-stream, then drives stages 3-5 (escrow → submit → poll).
        """
        console = Console()

        # The configured policy's parameters arrive through the injected
        # flags. One policy-owned namespace: declared flag values merged
        # with parsed --policy-param pairs.
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
        from .common import (
            resolve_fresh_buyer_identity,
            resolve_recovery_buyer_identity,
        )

        identity = (
            resolve_recovery_buyer_identity(from_run)
            if from_run
            else resolve_fresh_buyer_identity()
        )
        signer = identity.signer
        principal = identity.principal
        try:
            selected_funding_mode = FundingMode(funding_mode)
            selected_funding_profile = (
                FundingProfile(funding_profile) if funding_profile is not None else None
            )
            funding_selection = FundingSelection(
                mode=selected_funding_mode,
                instrument_ref=instrument_ref,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        buyer_settlement = resolve_buyer_settlement_policy(
            identity=identity,
            funding_selection=funding_selection,
            action_capable=action != "fail",
        )
        alkahest_config = buyer_settlement.config.mechanism_config("alkahest")
        stripe_config = buyer_settlement.config.mechanism_config("stripe")
        alkahest_enabled = bool(
            alkahest_config is not None and getattr(alkahest_config, "enabled", False)
        )
        stripe_enabled = bool(
            stripe_config is not None and getattr(stripe_config, "enabled", False)
        )
        hosted_requested = (
            funding_profile is not None
            or selected_funding_mode is not FundingMode.INTERACTIVE
            or instrument_ref is not None
            or automatic_funding
            or (stripe_enabled and not alkahest_enabled)
        )
        if hosted_requested and not stripe_enabled:
            raise typer.BadParameter(
                "--funding-profile requires enabled [Settlement.stripe]"
            )
        if not hosted_requested and not alkahest_enabled:
            raise typer.BadParameter("no buyer settlement mechanism is enabled")

        if from_run:
            if not is_negotiation_complete(from_run):
                typer.secho(
                    "Run-log has no agreed negotiation. Resume the round "
                    "loop with `market credits negotiate --from <run-id>` "
                    "first, then settle.",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            run_settle_from_log(
                identity=identity,
                run_id=from_run,
                escrow_uid=None,
                evm_address=evm_address,
                evm_private_key=evm_private_key,
                chain_name=chain_name,
                poll_interval=poll_interval,
                settlement_timeout=settlement_timeout,
                console=console,
                funding_mode=funding_mode,
                instrument_ref=instrument_ref,
                action=action,
                automatic_funding=automatic_funding,
            )
            return

        if quantity is None or quantity < 1:
            typer.secho(
                "Fresh `market credits buy` runs require --quantity >= 1 "
                "(how many credits to buy).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        from .common import resolve_key_disposition

        key_mode, resolved_key_id = resolve_key_disposition(
            new_key=new_key,
            key_id=key_id,
        )

        explicit_prices = initial_price is not None and max_price is not None
        if not explicit_prices and (initial_price is not None) != (
            max_price is not None
        ):
            typer.secho(
                "Pass both --initial-price and --max-price, or neither "
                "(in which case prices are derived from the advertised rate).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        # Resolution: CLI flag > config.toml > derivation > default.
        from .common import (
            APICREDITS_SCHEMA_ID,
            resolve_buyer_wallet,
            resolve_discovery_timeout,
            resolve_indexer_urls,
            resolve_indexer_urls_for_schema,
            resolve_registry_api_keys,
            resolve_registry_authorities,
            select_chain_for_listing,
        )

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
        evm_addr = evm_key = None
        chain_cfg = None
        selected_chain_name = None
        rpc = None
        addr_cfg = None
        if not hosted_requested:
            evm_addr, evm_key = resolve_buyer_wallet(
                override_addr=evm_address,
                override_pk=evm_private_key,
            )
            chain_cfg = select_chain_for_listing(
                listing=None,
                override=chain_name,
                yes=assume_yes,
            )
            selected_chain_name = chain_cfg.name
            rpc = chain_cfg.rpc_url
            addr_cfg = chain_cfg.alkahest_address_config_path
        missing = [name for name, value in (("registry_urls", reg_urls),) if not value]
        if not hosted_requested:
            missing.extend(
                name
                for name, value in (
                    ("buyer_evm_address", evm_addr),
                    ("buyer_evm_private_key", evm_key),
                )
                if not value
            )
        if missing:
            typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
            key_for = {
                "buyer_evm_address": "wallet.address",
                "buyer_evm_private_key": "wallet.private_key",
                "registry_urls": "registry.urls",
            }
            for name in missing:
                typer.secho(
                    f"  • {name} — set with: market config set {key_for[name]} <value>",
                    err=True,
                    fg=typer.colors.RED,
                )
            raise typer.Exit(2)

        # --token-contract acts as a filter on each candidate listing's
        # accepted_escrows. Explicit prices require it (decimals scaling).
        tc = token_contract
        if explicit_prices and not tc and not hosted_requested:
            typer.secho(
                "--initial-price and --max-price require --token-contract "
                "so prices can be scaled to the right decimals. Without it, "
                "drop the explicit price flags and let prices anchor on each "
                "listing's advertised per-token rate.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if explicit_prices and not hosted_requested:
            if token_decimals is None:
                from market_alkahest.token import resolve_token, TokenResolutionError

                try:
                    meta = resolve_token(
                        tc,
                        rpc_url=rpc,
                        chain_id=chain_cfg.chain_id,
                    )
                    token_decimals = meta.decimals
                except (TokenResolutionError, RuntimeError) as exc:
                    typer.secho(
                        f"Could not resolve token {tc} on chain {chain_cfg.name!r} — pass "
                        f"--token-decimals or check the chain's rpc_url. ({exc})",
                        err=True,
                        fg=typer.colors.RED,
                    )
                    raise typer.Exit(2)
            scale = 10 ** int(token_decimals)
            initial_price = initial_price * scale
            max_price = max_price * scale
        if explicit_prices and hosted_requested:
            if (
                not float(initial_price).is_integer()
                or not float(max_price).is_integer()
            ):
                raise typer.BadParameter(
                    "hosted explicit prices use integer currency minor units"
                )
            initial_price = int(initial_price)
            max_price = int(max_price)

        accepted_proposal_recipient = None

        def encode_escrow_proposal(value):
            return value

        def looks_like_propagation_lag(_exc):
            return False

        build_escrow_terms = None
        create_escrow = None
        make_alkahest_settlement_payload_fn = None
        if not hosted_requested:
            from .escrow_client import (
                accepted_proposal_recipient,
                encode_escrow_proposal,
                looks_like_propagation_lag,
                make_alkahest_settlement_payload_fn,
                make_buyer_payment_escrow_terms_fn,
                make_create_escrow_fn,
            )

            build_escrow_terms = make_buyer_payment_escrow_terms_fn(
                chain_name=selected_chain_name,
                addr_config_path=addr_cfg or None,
            )
            create_escrow = make_create_escrow_fn(
                private_key=evm_key,
                rpc_url=rpc,
                chain_name=selected_chain_name,
                addr_config_path=addr_cfg or None,
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
        if hosted_requested:
            clauses = ["mechanism=fiat.stripe.v1"]
            if selected_funding_profile is not None:
                clauses[0] += (
                    f" stripe.funding_profile={selected_funding_profile.value}"
                )
            clauses[0] += f" stripe.interaction={selected_funding_mode.value}"
            selected_matches = buyer_settlement.select_listings(
                matches,
                clauses=tuple(clauses),
                expiration_unix=expiration_unix,
            )
            matches = []
            for match, selected in selected_matches:
                normalized = dict(match)
                normalized["_selected_settlement"] = selected
                normalized["settlement_options"] = [
                    selected.option.model_dump(mode="json")
                ]
                matches.append(normalized)
            if not matches:
                typer.secho(
                    "No listings matched the exact hosted settlement constraints.",
                    err=True,
                    fg=typer.colors.YELLOW,
                )
                raise typer.Exit(0)

        # Listed-price default: when the buyer hasn't pinned both prices
        # explicitly, both anchor on the cheapest advertised per-token rate.
        if not explicit_prices:
            from core_buyer.cli import interactive_disposition

            initial_price, max_price = resolve_prices_from_matches(
                matches=matches,
                console=console,
                params=policy_params_all,
                interactive=interactive_disposition(assume_yes),
            )
            if initial_price is None or max_price is None:
                raise typer.Exit(2)

        aggregation_policy = (
            aggregate_by
            or resolve_config_value(
                toml_path="aggregation.policy",
            )
            or None
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
        provision = make_api_credits_provision_terms(
            quantity=int(quantity),
            key_mode=key_mode,
            key_id=resolved_key_id,
        )

        from .escrow_selection import select_escrow_entry

        def build_escrow_proposal_for_match(
            match: dict,
        ) -> EscrowProposal | Any | None:
            if hosted_requested:
                selected = match.get("_selected_settlement")
                if selected is None:
                    return None
                return selected.selection
            entry = select_escrow_entry(
                match,
                chain_name=selected_chain_name,
                token_contract_filter=tc,
                assume_yes=assume_yes,
                rpc_url=rpc,
                buyer_address=evm_addr,
                console=console,
                compatible=_policy.compatible,
                preference=_policy.prefer_settlement,
            )
            if entry is None:
                return None
            return escrow_proposal_from_accepted_entry(
                listing=match,
                entry=entry,
                expiration_unix=expiration_unix,
            )

        run_log = RunLog.start(
            profile_id=identity.profile_id,
            principal=identity.principal,
            command="market credits buy",
            buyer_evm_address=evm_addr,
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
            chain_name=selected_chain_name,
            settlement_mechanism=(
                "fiat.stripe.v1" if hosted_requested else "alkahest.v1"
            ),
            funding_profile=(
                selected_funding_profile.value
                if selected_funding_profile is not None
                else None
            ),
            funding_mode=selected_funding_mode.value if hosted_requested else None,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        header.add_row("Registries", ", ".join(reg_urls))
        header.add_row(
            "Marketplace principal", f"{principal.scheme.value}:{principal.identifier}"
        )
        if evm_addr:
            header.add_row("EVM chain wallet", evm_addr)
        else:
            header.add_row("Settlement", "hosted (wallet-free)")
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
        console.print(Panel(header, title="market credits buy", border_style="cyan"))

        def _observe(stage: str, body: dict) -> None:
            # Append a structured event to the run log so post-mortem
            # inspection and `--from` resume have something to read.
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
            elif stage == "hosted_settlement_poll":
                console.print(
                    f"[dim]hosted poll #{body.get('attempt')}[/dim]  "
                    f"status={body.get('status')}"
                )

        confirm_settlement_cb = None
        if not assume_yes and os.isatty(0):

            def confirm_settlement_cb(terms, listing):  # noqa: E306
                return _confirm_settlement_interactive(
                    terms=terms,
                    listing=listing,
                    quantity=int(quantity),
                    console=console,
                )

        # The chain is always built locally so the API-credits default
        # guards (answer_key_challenge) ride even with no [negotiation]
        # config — core's own default would use only the shape guard.
        from .common import resolve_negotiation_config

        policies, policy_mode = resolve_negotiation_config()
        negotiation_chain = load_buyer_chain(
            policies=policies,
            policy_mode=policy_mode,
            default_guards=buyer_policies.APICREDITS_BUYER_GUARDS,
        )

        negotiate_hook = make_negotiate_hook(
            config=config,
            constraints=constraints,
            provision=provision,
            unit_count=float(quantity),
            build_escrow_proposal=build_escrow_proposal_for_match,
            encode_escrow_proposal=encode_escrow_proposal,
            max_negotiation_rounds=max_rounds,
            derive_prices=None,
            chain=negotiation_chain,
            decode_provision_terms=ApiCreditsProvisionTerms.model_validate,
            decode_escrow_proposal=EscrowProposal.model_validate,
            decode_escrow_terms=EscrowTerms.model_validate,
        )
        if hosted_requested:
            action_policy = resolve_buyer_action_policy(
                action,
                interactive=os.isatty(0) and os.isatty(1),
            )
            hosted_confirm = None
            if not assume_yes and os.isatty(0):

                def _confirm_hosted(amount, _listing):
                    return typer.confirm(
                        f"Proceed with hosted settlement for {amount} minor units?",
                        default=True,
                    )

                hosted_confirm = _confirm_hosted
            settle_hook = make_hosted_settle_hook(
                config=config,
                mechanism=HOSTED_MECHANISM,
                prepare_authorization=lambda obligation_ref, obligation: (
                    prepare_hosted_funding_authorization(
                        buyer_profile_id=str(identity.profile_id),
                        principal=principal,
                        signer=signer,
                        stripe_config=stripe_config,
                        obligation_ref=obligation_ref,
                        obligation=obligation,
                        selection=funding_selection,
                        automatic=automatic_funding,
                    )
                ),
                poll_interval=poll_interval,
                total_timeout=settlement_timeout,
                sleep=time.sleep,
                action_policy=action_policy,
                open_url=webbrowser.open,
                print_url=typer.echo,
                confirm=hosted_confirm,
            )
        else:
            settle_hook = make_settle_hook(
                config=config,
                unit_count=float(quantity),
                duration_seconds=0,
                build_escrow_terms=build_escrow_terms,
                create_escrow=create_escrow,
                settlement_recipient=accepted_proposal_recipient,
                build_settlement_payload=make_alkahest_settlement_payload_fn(
                    buyer_evm_address=evm_addr,
                ),
                settlement_submit_max_attempts=6,
                settlement_submit_retryable=looks_like_propagation_lag,
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
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Buy failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        credentials = (
            result.tenant_credentials
            if isinstance(result.tenant_credentials, dict)
            else None
        )
        if credentials:
            # The durable copy — the seller returns the secret exactly once.
            run_log.event("credentials_delivered", credentials=credentials)

        run_log.end(
            result.status,
            seller_url=result.seller_url,
            negotiation_id=result.negotiation_id,
            agreed_amount=result.agreed_amount,
            escrow_uid=result.escrow_uid,
            fulfillment_uid=result.fulfillment_uid,
            reason=result.reason,
        )

        # Render the final outcome.
        tbl = Table.grid(padding=(0, 2))
        tbl.add_column(style="bold")
        tbl.add_column()
        tbl.add_row("Status", result.status)
        for label, val in (
            ("Seller", result.seller_url),
            ("Negotiation", result.negotiation_id),
            ("Agreed amount (total)", result.agreed_amount),
            ("Escrow UID", result.escrow_uid),
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

        if credentials:
            render_credentials(console, credentials)

        if result.status != "ready":
            raise typer.Exit(4)

    register_policy_verb(credits_app, "buy", buy, _policy)
