"""`market credits negotiate` — buyer-as-client sync negotiation, one deal.

Thin wrapper around ``core_buyer.negotiation_client``. Prices are
per-token rates; the requested ``--quantity`` is the unit count that
scales them to the absolute amounts the negotiation runs on. The key
disposition (``--new-key`` / ``--key-id``) is fixed at round 0 inside
the provision terms, exactly like the VM lease duration.
"""

from __future__ import annotations

from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import domains.apicredits.negotiation.buyer_policies as buyer_policies  # registers answer_key_challenge
from .buyer_client import ResumeState, load_buyer_chain, negotiate_with_seller
from core_buyer.deal_helpers import load_negotiation_resume_point
from core_buyer.run_log import RunLog
from domains.apicredits.negotiation import make_api_credits_provision_terms

from .cli_helpers import resolve_prices_from_matches


def register(credits_app: typer.Typer) -> None:
    """Register `market credits negotiate`.

    Pricing flags come from the configured negotiation policy
    (ARCHITECTURE.md, "Buyer negotiation policy surface"), injected at
    app assembly — the scalar policies contribute --initial-price/
    --max-price/--price-markup, plus the --policy-param escape hatch.
    """
    from core_buyer.cli import assume_yes_option, register_policy_verb
    from core_buyer.policy_surface import configured_buyer_policy

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

        from core_buyer.cli import parse_key_value_options

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

        from .common import (
            make_run_publisher_principals_refresh,
            resolve_buyer_wallet,
            resolve_fresh_buyer_identity,
            resolve_key_disposition,
            resolve_recovery_buyer_identity,
        )

        identity = (
            resolve_recovery_buyer_identity(from_run)
            if from_run
            else resolve_fresh_buyer_identity()
        )
        signer = identity.signer
        principal = identity.principal
        evm_addr, _evm_key = resolve_buyer_wallet(
            override_addr=evm_address,
            override_pk=evm_private_key,
        )
        if not evm_addr:
            typer.secho(
                "Missing EVM address required to select and inspect the Alkahest "
                "escrow. Pass --evm-address or configure wallet.address.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)

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

        from .common import (
            APICREDITS_SCHEMA_ID,
            resolve_discovery_timeout,
            resolve_indexer_urls,
            resolve_indexer_urls_for_schema,
            resolve_registry_api_keys,
            resolve_registry_authorities,
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

        # Fetch the listing — needed for both --seller auto-resolution
        # and picking an accepted_escrows entry. Skipped in resume mode.
        listing_dict: Optional[dict] = None
        if listing_id and resume_state is None:
            from core_buyer.orchestrator import fetch_listing_dict

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
            # Fill missing prices from the listing's advertised rate —
            # same listed-price default as `market credits buy`.
            if initial_price is None or max_price is None:
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
                "registry-discoverable listing_id with an advertised rate).",
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

        # Pick one accepted_escrows entry — token, escrow contract, and
        # chain all come from the listing. ``--token-contract`` (when
        # set) filters entries to one ERC-20.
        from .escrow_selection import select_escrow_entry
        from .common import select_chain_for_listing

        picked_entry: Optional[dict] = None
        chain_cfg = None
        if listing_dict is not None:
            chain_cfg = select_chain_for_listing(
                listing=listing_dict,
                override=chain_name,
                yes=assume_yes,
            )

            picked_entry = select_escrow_entry(
                listing_dict,
                chain_name=chain_cfg.name,
                token_contract_filter=token_contract,
                assume_yes=assume_yes,
                rpc_url=chain_cfg.rpc_url,
                buyer_address=evm_addr,
                console=console,
                compatible=_policy.compatible,
                preference=_policy.prefer_settlement,
            )
            if picked_entry is None:
                msg = (
                    f"Listing {listing_id!r} has no accepted_escrows entry on "
                    f"chain {chain_cfg.name!r}"
                )
                if token_contract:
                    msg += f" with token {token_contract}"
                typer.secho(msg + ".", err=True, fg=typer.colors.RED)
                raise typer.Exit(2)
            from market_alkahest.schemas import accepted_token_address

            entry_token = accepted_token_address(picked_entry)
            if isinstance(entry_token, str) and entry_token.startswith("0x"):
                token_contract = entry_token

        # Scale explicit --initial-price / --max-price from human /
        # whole-token units to base units. Sellers publish per-token
        # rates in base units; buyer ceilings need the same scale.
        if _initial_explicit or _max_explicit:
            decimals: Optional[int] = (
                int(token_decimals) if token_decimals is not None else None
            )
            if decimals is None:
                from market_alkahest.token import (
                    resolve_token,
                    TokenResolutionError,
                )

                tc = token_contract
                if tc and chain_cfg is not None:
                    try:
                        meta = resolve_token(
                            tc,
                            rpc_url=chain_cfg.rpc_url,
                            chain_id=chain_cfg.chain_id,
                        )
                        decimals = meta.decimals
                    except (TokenResolutionError, RuntimeError):
                        decimals = None
            if decimals is None:
                typer.secho(
                    "Could not resolve token decimals to scale prices. "
                    "Pass --token-decimals or ensure the listing's accepted "
                    "chain is configured in [chains.<name>].",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            scale = 10 ** int(decimals)
            if _initial_explicit and initial_price is not None:
                initial_price = initial_price * scale
            if _max_explicit and max_price is not None:
                max_price = max_price * scale

        from market_identity import TrustedIdentitySet

        expected_seller_principals = (
            resume_point.publisher_principals
            if resume_point is not None
            else TrustedIdentitySet.model_validate(
                (listing_dict or {}).get("publisher_principals"),
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
            chain_name=(chain_cfg.name if chain_cfg is not None else None),
        )
        from core_buyer.orchestration import make_publisher_trust_resolver
        from core_buyer.orchestrator import BuyConfig

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

        # Build provision + escrow proposal for the negotiate request.
        from market_alkahest.proposals import escrow_proposal_from_accepted_entry
        import time as _time

        provision_terms = None
        escrow_proposal = None
        if resume_state is None:
            assert quantity is not None  # gated above
            assert picked_entry is not None  # listing fetched + entry picked above
            provision_terms = make_api_credits_provision_terms(
                quantity=int(quantity),
                key_mode=key_mode,
                key_id=resolved_key_id,
            )
            escrow_proposal = escrow_proposal_from_accepted_entry(
                listing=listing_dict or {},
                entry=picked_entry,
                expiration_unix=int(_time.time()) + 3600,
            )

        # Honor optional [negotiation] policies / policy_mode overrides
        # in buyer.toml; a resume continues under the policy that opened
        # the negotiation. Either way the chain is loaded with the
        # API-credits default guards so answer_key_challenge always rides.
        from .common import resolve_negotiation_config

        policies, policy_mode = resolve_negotiation_config()
        if resume_state is not None and not (policies or policy_mode):
            policy_mode_from_log = getattr(resume_point, "policy", None)
            if policy_mode_from_log:
                policy_mode = str(policy_mode_from_log)
        chain = load_buyer_chain(
            policies=policies,
            policy_mode=policy_mode,
            default_guards=buyer_policies.APICREDITS_BUYER_GUARDS,
        )

        try:
            outcome = negotiate_with_seller(
                seller_url=seller_url,
                principal=principal,
                signer=signer,
                listing_id=listing_id,
                initial_price=initial_price or 0,
                max_price=max_price,
                unit_count=(float(quantity) if resume_state is None else None),
                provision_terms=provision_terms,
                escrow_proposal=escrow_proposal,
                max_rounds=max_rounds,
                on_round=_observe,
                resume=resume_state,
                chain=chain,
                policy_params=policy_params_all,
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
