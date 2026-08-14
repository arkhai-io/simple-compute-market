"""`market negotiate` — buyer-as-client sync negotiation, one deal.

Thin wrapper around buyer_client.negotiate_with_seller(). Demonstrates
the pattern end-to-end: the CLI makes no agent assumptions, runs
entirely as an HTTP client talking to the seller.

Intended as a building block for the full market-buy rewrite; for now,
exists to exercise /negotiate/new + /negotiate/{id} directly.
"""

from __future__ import annotations

from typing import Any

import typer
from market_core.schemas import SettlementSelection
from market_identity import TrustedIdentitySet
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .buyer_client import ResumeState, negotiate_with_seller
from .cli_helpers import resolve_prices_from_matches
from .deal_helpers import (
    load_negotiation_resume_point,
    make_publisher_trust_resolver,
)
from .run_log import RunLog


def _normalize_start_utc(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "now":
        return None
    return text


def register(app: typer.Typer) -> None:
    """Register the top-level `market negotiate` command.

    Pricing flags come from the configured negotiation policy
    (ARCHITECTURE.md, "Buyer negotiation policy surface"), injected at app assembly —
    the scalar policies contribute --initial-price/--max-price/
    --price-markup, plus the --policy-param escape hatch.
    """
    from core_buyer.cli import assume_yes_option, register_policy_verb

    from .policy_surface import configured_buyer_policy

    _policy = configured_buyer_policy()

    def negotiate(  # registered below after policy-param injection
        seller_url: str | None = typer.Option(
            None,
            "--seller",
            "-s",
            help="Seller agent base URL. Optional — resolved from the "
            "registry given --listing-id; resumed runs (--from) "
            "read it from the run-log. Pass explicitly to override.",
        ),
        listing_id: str | None = typer.Option(
            None,
            "--listing-id",
            help="The seller's listing_id. Required for fresh runs; "
            "resumed runs (--from) read it from the run-log.",
        ),
        registry_urls: str | None = typer.Option(
            None,
            "--registry-urls",
            help="Comma-separated registry base URLs (default: "
            "registry.urls from config.toml). Used to resolve the "
            "seller URL and price floor from a listing_id; the "
            "first registry that knows the listing wins.",
        ),
        discovery_timeout: float | None = typer.Option(
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
        from_run: str | None = typer.Option(
            None,
            "--from",
            help="Resume the round loop of a prior `market negotiate` run "
            "(by run-id). Skips /negotiate/new; replays the seller's "
            "last counter into the strategy and continues. Useful "
            "when the buyer crashed mid-round but the seller's "
            "thread state is still live.",
        ),
        duration_hours: float | None = typer.Option(
            None,
            "--duration-hours",
            "-t",
            help="Lease duration the buyer wants (hours, fractional ok). "
            "Required for fresh runs — sent on /negotiate/new and "
            "validated server-side against the listing's max_duration_seconds. "
            "Resumed runs read it from the run-log.",
        ),
        start_utc: str | None = typer.Option(
            None,
            "--start-utc",
            help="Requested lease start time in UTC (ISO-8601 or YYYY-MM-DD HH:MM). "
            "Omit or pass 'now' for immediate start.",
        ),
        token_contract: str | None = typer.Option(
            None,
            "--token-contract",
            help="Optional ERC-20 accepted-escrow filter. Omit to use the "
            "token/escrow shape selected from the listing.",
        ),
        token_decimals: float | None = typer.Option(
            None,
            "--token-decimals",
            help="ERC-20 token decimals override for scaling price flags. "
            "Only needed when decimals cannot be resolved on chain.",
        ),
        chain_name: str | None = typer.Option(
            None,
            "--chain",
            help="Which [chains.<name>] entry to negotiate against. When "
            "omitted the buyer prompts; required when --yes is set "
            "and the listing accepts more than one chain you have configured.",
        ),
        **policy_values: Any,
    ) -> None:
        """Drive a synchronous negotiation with one seller, round-by-round.

        Each round is a signed HTTP POST to the seller. The seller's
        policy decides counter/accept/exit and returns the decision
        inline. The buyer's policy decides locally in this process
        (default: listed_price — pay what's published).
        """
        console = Console()

        from core_buyer.cli import parse_key_value_options

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
        initial_price: float | None = policy_params_all.get("initial_price")
        max_price: float | None = policy_params_all.get("max_price")

        # Capture which prices the user passed explicitly — auto-derived
        # values (from the listing's advertised min_price) are already
        # in base units and must not be scaled again below.
        _initial_explicit = initial_price is not None
        _max_explicit = max_price is not None

        from .common import (
            resolve_buyer_signer,
            resolve_identity_config,
            resolve_identity_credential,
        )

        identity_config = resolve_identity_config()
        signer = resolve_buyer_signer(
            identity_config,
            resolve_identity_credential(),
        )

        resume_state = None
        if from_run:
            resume_point = load_negotiation_resume_point(from_run, signer=signer)
            seller_url = seller_url or resume_point.seller_url
            listing_id = listing_id or resume_point.listing_id
            if max_price is None:
                typer.secho(
                    "--max-price is required when resuming (the strategy "
                    "needs the buyer's ceiling).",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            resume_state = ResumeState(
                negotiation_id=resume_point.negotiation_id,
                transcript=resume_point.transcript,
                last_seller_proposal=resume_point.last_seller_proposal,
                rounds_completed=resume_point.rounds_completed,
            )

        # Resolve and authenticate registry discovery separately from the
        # standalone negotiation's explicit Alkahest wallet.
        from .common import (
            VMS_SCHEMA_ID,
            resolve_discovery_timeout,
            resolve_indexer_urls,
            resolve_indexer_urls_for_schema,
            resolve_registry_api_keys,
            resolve_registry_authorities,
        )

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

        # Fetch the listing — needed for both --seller auto-resolution
        # and picking an accepted_escrows entry. Skipped in resume mode
        # (the saved run-log carries the prior commitments).
        listing_dict: dict | None = None
        if listing_id and resume_state is None:
            from .buy_orchestrator import fetch_listing_dict

            source_registry_url: str | None = None
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
                    source_registry_url = registry_url
                    break
            if not listing_dict or source_registry_url is None:
                detail = f": {last_error}" if last_error is not None else ""
                typer.secho(
                    f"No listing {listing_id!r} in any of "
                    f"{len(reg_urls)} registries{detail}.",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            listing_dict["source_registry_url"] = source_registry_url
            listing_dict["source_registry_authority"] = registry_authorities[
                source_registry_url
            ].authority
            if not seller_url:
                seller_url = listing_dict.get("storefront_url")
                if not seller_url:
                    typer.secho(
                        f"Listing {listing_id} has no `storefront_url` field; "
                        "pass --seller explicitly.",
                        err=True,
                        fg=typer.colors.RED,
                    )
                    raise typer.Exit(2)
            # Fill missing prices from the listing's advertised rate —
            # same listed-price default as `market buy`.
            if initial_price is None or max_price is None:
                # Non-interactive even in a TTY: the listing here was
                # the user's own explicit choice — there is no unseen
                # discovery pick to confirm.
                initial_price, max_price = resolve_prices_from_matches(
                    matches=[listing_dict],
                    console=console,
                    params=policy_params_all,
                )
                if initial_price is None or max_price is None:
                    raise typer.Exit(2)

        if not seller_url or not listing_id:
            typer.secho(
                "Missing required negotiation inputs. For a fresh run pass "
                "--listing-id (and optionally --seller); for a resume pass --from <run-id>.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        if resume_state is None and (initial_price is None or max_price is None):
            typer.secho(
                "Fresh runs require --initial-price and --max-price (or a "
                "registry-discoverable listing_id with an advertised min_price).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if resume_state is None and (duration_hours is None or duration_hours <= 0):
            typer.secho(
                "Fresh runs require --duration-hours (the buyer's lease ask).",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        duration_seconds = (
            round(duration_hours * 3600) if duration_hours is not None else None
        )
        requested_start_utc = _normalize_start_utc(start_utc)

        selected_settlement = None
        settlement_policy = None
        picked_entry: dict | None = None
        chain_cfg = None
        if listing_dict is not None:
            import time as _time

            from .settlement_composition import (
                alkahest_entry_from_selection,
                resolve_buyer_settlement_policy,
            )

            try:
                settlement_policy = resolve_buyer_settlement_policy()
                selected_settlement = settlement_policy.select(
                    listing_dict,
                    expiration_unix=int(_time.time()) + 3600,
                )
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            if selected_settlement is None:
                raise typer.BadParameter(
                    f"listing {listing_id!r} has no installed, enabled, compatible "
                    "settlement option"
                )

            if selected_settlement.registration.config_key == "alkahest":
                from market_alkahest.schemas import accepted_token_address

                from .common import chain_by_name, resolve_buyer_wallet

                picked_entry = alkahest_entry_from_selection(selected_settlement)
                if picked_entry is None:
                    raise typer.BadParameter(
                        "selected Alkahest option has no accepted escrow"
                    )
                if not _policy.compatible(picked_entry):
                    raise typer.BadParameter(
                        "selected Alkahest option is incompatible with buyer policy"
                    )
                advertised_chain = picked_entry.get("chain_name")
                if not isinstance(advertised_chain, str) or not advertised_chain:
                    raise typer.BadParameter(
                        "selected Alkahest option has no chain identity"
                    )
                if chain_name is not None and chain_name != advertised_chain:
                    raise typer.BadParameter(
                        "selected Alkahest option does not use the requested chain"
                    )
                chain_cfg = chain_by_name(advertised_chain)
                addr, pk = resolve_buyer_wallet()
                if not addr or not pk:
                    raise typer.BadParameter(
                        "selected Alkahest settlement requires [Wallet] credentials"
                    )
                entry_token = accepted_token_address(picked_entry)
                if isinstance(entry_token, str) and entry_token.startswith("0x"):
                    if (
                        token_contract is not None
                        and entry_token.lower() != token_contract.lower()
                    ):
                        raise typer.BadParameter(
                            "selected Alkahest option does not use --token-contract"
                        )
                    token_contract = entry_token

                if _initial_explicit or _max_explicit:
                    decimals: int | None = (
                        int(token_decimals) if token_decimals is not None else None
                    )
                    if decimals is None:
                        from market_alkahest.token import (
                            TokenResolutionError,
                            resolve_token,
                        )

                        try:
                            decimals = resolve_token(
                                token_contract,
                                rpc_url=chain_cfg.rpc_url,
                                chain_id=chain_cfg.chain_id,
                            ).decimals
                        except (TokenResolutionError, RuntimeError):
                            decimals = None
                    if decimals is None:
                        raise typer.BadParameter(
                            "could not resolve selected Alkahest token decimals"
                        )
                    scale = 10**decimals
                    if _initial_explicit and initial_price is not None:
                        initial_price = initial_price * scale
                    if _max_explicit and max_price is not None:
                        max_price = max_price * scale

        if listing_dict is not None:
            expected_seller_principals = TrustedIdentitySet.model_validate(
                listing_dict.get("publisher_principals")
            )
            publisher_id = str(listing_dict.get("publisher_id") or "").strip()
            source_registry_url = str(
                listing_dict.get("source_registry_url") or ""
            ).strip()
            source_registry_authority = str(
                listing_dict.get("source_registry_authority") or ""
            ).strip()
        else:
            expected_seller_principals = resume_point.publisher_principals
            publisher_id = resume_point.publisher_id
            source_registry_url = resume_point.source_registry_url
            source_registry_authority = resume_point.source_registry_authority
        if not publisher_id or not source_registry_url or not source_registry_authority:
            raise typer.BadParameter("listing publisher provenance is incomplete")
        run_log = RunLog.start(
            command="market negotiate",
            principal=identity_config.principal,
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
            duration_seconds=duration_seconds,
            resumed_from=from_run,
            **(
                settlement_policy.public_run_metadata()
                if settlement_policy is not None
                else {}
            ),
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        if from_run:
            header.add_row("Resumed from", from_run)
        header.add_row("Seller", seller_url)
        header.add_row("Listing", listing_id)
        if initial_price is not None:
            header.add_row("Opening bid", str(initial_price))
        header.add_row("Ceiling", str(max_price))
        header.add_row("Max rounds", str(max_rounds))
        console.print(Panel(header, title="market negotiate", border_style="cyan"))

        round_table = Table(title="Rounds", show_lines=False)
        round_table.add_column("#")
        round_table.add_column("Our action")
        round_table.add_column("Our price")
        round_table.add_column("Seller action")
        round_table.add_column("Seller price")

        def _observe(round_idx: int, our_msg: dict, reply: dict) -> None:
            run_log.event(
                "negotiation_round",
                round=round_idx,
                our_message=our_msg,
                their_reply=reply,
            )
            round_table.add_row(
                str(round_idx),
                str(our_msg.get("action", "propose")),
                str(our_msg.get("price") or our_msg.get("initial_price") or "-"),
                str(reply.get("action", "-")),
                str(reply.get("price", "-")),
            )

        # Build provision + escrow proposal for the negotiate request.
        # The standalone `market negotiate` subcommand doesn't reach
        # settlement, so the escrow proposal is largely a formality
        # (the seller still validates it). Resume mode skips the
        # round-0 send and these fields are ignored.
        from arkhai_vms import VmProvisionTerms, make_vm_provision_terms
        from market_alkahest.schemas import EscrowProposal

        from domains.vms.settlement import escrow_proposal_from_accepted_entry

        provision_terms: VmProvisionTerms | None = None
        escrow_proposal: EscrowProposal | None = None
        settlement_selection: SettlementSelection | None = None
        if resume_state is None:
            assert duration_seconds is not None
            assert selected_settlement is not None
            provision_terms = make_vm_provision_terms(
                duration_seconds=int(duration_seconds),
                start_utc=requested_start_utc,
                ssh_public_key="",
            )
            if selected_settlement.registration.config_key == "stripe":
                settlement_selection = selected_settlement.selection
            else:
                assert picked_entry is not None
                escrow_proposal = escrow_proposal_from_accepted_entry(
                    listing=listing_dict or {},
                    entry=picked_entry,
                    expiration_unix=selected_settlement.selection.expiration_unix,
                )

        # Honor optional [negotiation] policies / policy_mode overrides
        # in buyer.toml, mirroring the seller's [negotiation] knob.
        # `policies` is the explicit ordered list; `policy_mode` is the
        # legacy single-terminal key. The buyer wheel installs without
        # torch by default — set "bisection" to avoid the RL self-register
        # path blowing up. When both are unset, negotiate_with_seller
        # falls through to its default chain.
        chain = None
        from .common import resolve_negotiation_config

        policies, policy_mode = resolve_negotiation_config()
        if resume_state is not None and not (policies or policy_mode):
            # A resume continues under the policy that opened the
            # negotiation (recorded at run start), not whatever the
            # config resolves to today.
            policy_mode_from_log = getattr(resume_point, "policy", None)
            if policy_mode_from_log:
                policy_mode = str(policy_mode_from_log)
        if policies or policy_mode:
            from .buyer_client import load_buyer_chain

            chain = load_buyer_chain(policies=policies, policy_mode=policy_mode)

        resolve_seller_principals = make_publisher_trust_resolver(
            run_id=run_log.run_id,
            listing_id=listing_id,
            publisher_id=publisher_id,
            source_registry_url=source_registry_url,
            source_registry_authority=source_registry_authority,
            current=expected_seller_principals,
            signer=signer,
        )

        try:
            outcome = negotiate_with_seller(
                seller_url=seller_url,
                principal=identity_config.principal,
                signer=signer,
                listing_id=listing_id,
                initial_price=initial_price or 0,
                max_price=max_price,
                provision_terms=provision_terms,
                escrow_proposal=escrow_proposal,
                settlement_selection=settlement_selection,
                max_rounds=max_rounds,
                on_round=_observe,
                resume=resume_state,
                chain=chain,
                resolve_seller_principals=resolve_seller_principals,
                policy_params=policy_params_all,
            )
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Negotiation failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3) from exc

        from core_buyer.deal_helpers import settlement_acceptance_fields

        accepted_settlement = settlement_acceptance_fields(
            negotiation_id=outcome.negotiation_id or "",
            selection=outcome.settlement_selection,
            plan=outcome.settlement_plan,
        )
        run_log.end(
            outcome.status,
            negotiation_id=outcome.negotiation_id,
            agreed_amount=outcome.agreed_amount,
            rounds=outcome.rounds,
            reason=outcome.reason,
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

        console.print(round_table)

        result_table = Table.grid(padding=(0, 2))
        result_table.add_column(style="bold")
        result_table.add_column()
        result_table.add_row("Status", outcome.status)
        if outcome.negotiation_id:
            result_table.add_row("Negotiation", outcome.negotiation_id)
        if outcome.agreed_amount is not None:
            result_table.add_row("Agreed price", str(outcome.agreed_amount))
        if outcome.reason:
            result_table.add_row("Reason", outcome.reason)
        result_table.add_row("Rounds", str(outcome.rounds))

        border = "green" if outcome.status == "agreed" else "yellow"
        console.print(Panel(result_table, title="Outcome", border_style=border))

        if outcome.status != "agreed":
            raise typer.Exit(4)

    register_policy_verb(app, "negotiate", negotiate, _policy)
