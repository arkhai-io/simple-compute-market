"""`market tokens buy` — pure-client sequential token buy.

Drives the deal end-to-end from the CLI process:

    discover (registry, api-tokens schema) →
    negotiate each match (sync HTTP rounds, quantity × per-token rate) →
    pick agreed match →
    create escrow on-chain (alkahest-py in-process) →
    POST /settle/{uid} on seller →
    poll /settle/{uid}/status until ready/failed →
    deliver the issued credentials to the run-log.

The orchestration stages are core (``core_buyer.orchestration``); this
command wires the API-tokens instantiation: the quantity unit count,
the key disposition fixed at round 0, the durationless escrow terms,
and the once-only credential delivery.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import domains.apitokens.negotiation.buyer_policies as buyer_policies  # registers answer_key_challenge
from core_buyer import (
    BuyConfig,
    BuyConstraints,
    query_registry_for_matches_multi,
    run_buy,
)
from core_buyer.deal_helpers import is_negotiation_complete
from core_buyer.negotiation_client import _load_buyer_chain
from core_buyer.orchestration import make_negotiate_hook, make_settle_hook
from core_buyer.run_log import RunLog
from domains.apitokens.negotiation import make_api_tokens_provision_terms
from market_alkahest.proposals import escrow_proposal_from_accepted_entry
from market_alkahest.schemas import EscrowProposal

from .cli_helpers import resolve_prices_from_matches
from .common import resolve_config_value
from .settle_cli import render_credentials, run_settle_from_log


def _confirm_settlement_interactive(
    *, terms, listing: dict, quantity: int, console: Console,
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
        return typer.confirm("Proceed to settlement (escrow + /settle + poll)?", default=True)
    except typer.Abort:
        return False


def register(tokens_app: typer.Typer) -> None:
    """Register `market tokens buy`.

    Pricing flags are not defined here: the configured negotiation
    policy contributes its own parameter surface at app-assembly time
    (ARCHITECTURE.md, "Buyer negotiation policy surface") — the scalar
    policies contribute --initial-price/--max-price/--price-markup
    (per-token rates), plus the --policy-param escape hatch.
    """
    import os

    from market_policy.buyer_policy import inject_policy_cli_params

    from core_buyer.policy_surface import configured_buyer_policy

    _policy = configured_buyer_policy()

    def buy(  # registered below after policy-param injection
        assume_yes: bool = typer.Option(
            False, "--yes", "-y",
            help="Skip ALL interactive prompts (price defaults + "
                 "pre-settlement confirmation). Set this for scripts, CI, "
                 "or non-interactive runs.",
        ),
        quantity: Optional[int] = typer.Option(
            None, "--quantity", "-n",
            help="How many tokens (credits) to buy. Required for fresh "
                 "runs — fixed at round 0 in the provision terms and the "
                 "unit count that scales per-token prices to absolute "
                 "amounts. Resumed runs read the prior totals from the run-log.",
        ),
        new_key: bool = typer.Option(
            False, "--new-key",
            help="Issue a fresh API key for this purchase (the default "
                 "disposition; the seller binds it to your wallet).",
        ),
        key_id: Optional[str] = typer.Option(
            None, "--key-id",
            help="Top up an existing key instead of issuing a new one. "
                 "v1 sellers reject unless the key is bound to the "
                 "purchasing wallet (or carries no ownership claim).",
        ),
        service_name: Optional[str] = typer.Option(
            None, "--service-name",
            help="Filter listings by service name (registry-side contains match).",
        ),
        raw_filters: Optional[list[str]] = typer.Option(
            None, "--filter", "-f",
            help="Registry filter-spec parameter as name=value. Repeatable.",
        ),
        from_run: Optional[str] = typer.Option(
            None, "--from",
            help="Resume a partial buy run-id end-to-end. Continues "
                 "negotiation if it stopped mid-stream, then drives "
                 "escrow.create + /settle + poll. The same run-log is "
                 "appended to, so it captures the full lifecycle.",
        ),
        registry_urls: Optional[str] = typer.Option(
            None, "--registry-urls",
            help="Comma-separated registry base URLs (default: "
                 "registry.urls from config.toml). Discovery is the "
                 "union across all listed registries, deduped by listing_id.",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None, "--discovery-timeout",
            help="Per-registry deadline in seconds (default: "
                 "registry.discovery_timeout from config.toml, fallback 5).",
        ),
        token_contract: Optional[str] = typer.Option(
            None, "--token-contract",
            help="Optional filter: only consider listings whose accepted "
                 "escrow uses this ERC-20. Required when passing explicit "
                 "--initial-price/--max-price (decimals scaling).",
        ),
        token_decimals: Optional[int] = typer.Option(
            None, "--token-decimals",
            help="ERC-20 token decimals override. When omitted, decimals "
                 "are resolved on chain via the token contract's "
                 "decimals() view.",
        ),
        chain_name: Optional[str] = typer.Option(
            None, "--chain",
            help="Pick which configured [chains.<name>] entry to operate on. "
                 "Required when --yes is set and the buyer has more than one "
                 "chain configured; otherwise the buyer prompts.",
        ),
        expiration_seconds: int = typer.Option(
            3600, "--expiration",
            help="Escrow deadline (seconds from now) for the "
                 "reclaim_expired escape hatch. Default 1h.",
        ),
        max_matches: int = typer.Option(
            5, "--max-matches",
            help="How many matching seller listings to try before giving up.",
        ),
        aggregate_by: Optional[str] = typer.Option(
            None, "--aggregate-by",
            help="Across-seller aggregation policy. Default: "
                 "[aggregation].policy from buyer.toml, falling "
                 "back to 'best_price'.",
        ),
        max_rounds: int = typer.Option(
            10, "--max-rounds",
            help="Per-negotiation round cap.",
        ),
        poll_interval: float = typer.Option(
            5.0, "--poll-interval",
            help="Seconds between /settle/status polls.",
        ),
        settlement_timeout: float = typer.Option(
            600.0, "--settlement-timeout",
            help="Max seconds to wait for issuance before giving up.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet address (default: derived from wallet.private_key).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        **policy_values: Any,
    ) -> None:
        """Buy API tokens end-to-end as a pure HTTP/web3 client.

        No buyer agent is started or consulted; every step is either a
        signed HTTP call to a seller, a registry query, or a direct
        on-chain call. The issued credentials are shown once and saved
        to the run-log.

        When ``--from <run_id>`` is supplied, picks up wherever the
        prior run left off: finishes the negotiation if it stopped
        mid-stream, then drives stages 3-5 (escrow → submit → poll).
        """
        console = Console()

        from core_buyer.cli import parse_filter_options

        # The configured policy's parameters arrive through the injected
        # flags. One policy-owned namespace: declared flag values merged
        # with parsed --policy-param pairs.
        policy_params_all: dict[str, Any] = {
            k: v for k, v in policy_values.items() if k != "policy_param"
        }
        policy_params_all.update(parse_filter_options(
            policy_values.get("policy_param") or [],
        ))
        initial_price: Optional[float] = policy_params_all.get("initial_price")
        max_price: Optional[float] = policy_params_all.get("max_price")

        if from_run:
            if not is_negotiation_complete(from_run):
                typer.secho(
                    "Run-log has no agreed negotiation. Resume the round "
                    "loop with `market tokens negotiate --from <run-id>` "
                    "first, then settle.",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            run_settle_from_log(
                run_id=from_run,
                escrow_uid=None,
                buyer_address=buyer_address,
                buyer_private_key=buyer_private_key,
                chain_name=chain_name,
                poll_interval=poll_interval,
                settlement_timeout=settlement_timeout,
                console=console,
            )
            return

        if quantity is None or quantity < 1:
            typer.secho(
                "Fresh `market tokens buy` runs require --quantity >= 1 "
                "(how many tokens to buy).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        from .common import resolve_key_disposition
        key_mode, resolved_key_id = resolve_key_disposition(
            new_key=new_key, key_id=key_id,
        )

        explicit_prices = initial_price is not None and max_price is not None
        if not explicit_prices and (initial_price is not None) != (max_price is not None):
            typer.secho(
                "Pass both --initial-price and --max-price, or neither "
                "(in which case prices are derived from the advertised rate).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        # Resolution: CLI flag > config.toml > derivation > default.
        from .common import (
            APITOKENS_SCHEMA_ID,
            build_token_filter_params,
            resolve_buyer_wallet,
            resolve_indexer_urls_for_schema,
            resolve_discovery_timeout, resolve_indexer_auth,
            select_chain_for_listing,
        )
        addr, pk = resolve_buyer_wallet(
            override_addr=buyer_address, override_pk=buyer_private_key,
        )
        reg_urls = resolve_indexer_urls_for_schema(APITOKENS_SCHEMA_ID, override=registry_urls)
        deadline = resolve_discovery_timeout(override=discovery_timeout)
        reg_auth = resolve_indexer_auth()
        # Pick a chain up-front when there's no listing context yet; the
        # orchestrator only considers listings that accept this chain.
        chain_cfg = select_chain_for_listing(
            listing=None, override=chain_name, yes=assume_yes,
        )
        selected_chain_name = chain_cfg.name
        rpc = chain_cfg.rpc_url
        addr_cfg = chain_cfg.alkahest_address_config_path

        _key_for = {
            "buyer_priv_key": "wallet.private_key",
            "registry_urls": "registry.urls",
        }
        missing = [n for n, v in (
            ("buyer_priv_key", pk),
            ("registry_urls", reg_urls),
        ) if not v]
        if missing:
            typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
            for name in missing:
                typer.secho(
                    f"  • {name} — set with: market config set {_key_for[name]} <value>",
                    err=True, fg=typer.colors.RED,
                )
            raise typer.Exit(2)

        # --token-contract acts as a filter on each candidate listing's
        # accepted_escrows. Explicit prices require it (decimals scaling).
        tc = token_contract
        if explicit_prices and not tc:
            typer.secho(
                "--initial-price and --max-price require --token-contract "
                "so prices can be scaled to the right decimals. Without it, "
                "drop the explicit price flags and let prices anchor on each "
                "listing's advertised per-token rate.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if explicit_prices:
            if token_decimals is None:
                from market_alkahest.token import resolve_token, TokenResolutionError
                try:
                    meta = resolve_token(
                        tc, rpc_url=rpc, chain_id=chain_cfg.chain_id,
                    )
                    token_decimals = meta.decimals
                except (TokenResolutionError, RuntimeError) as exc:
                    typer.secho(
                        f"Could not resolve token {tc} on chain {chain_cfg.name!r} — pass "
                        f"--token-decimals or check the chain's rpc_url. ({exc})",
                        err=True, fg=typer.colors.RED,
                    )
                    raise typer.Exit(2)
            scale = 10 ** int(token_decimals)
            initial_price = initial_price * scale
            max_price = max_price * scale

        # Escrow-terms builder + on-chain submit hook, env-config-closed
        # at this layer so the orchestrator doesn't see chain creds.
        from core_buyer.escrow_client import (
            make_buyer_payment_escrow_terms_fn,
            make_create_escrow_fn,
        )
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

        # Filter-aware discovery.
        active_filters = build_token_filter_params(service_name=service_name)
        active_filters.update(parse_filter_options(raw_filters))
        try:
            matches = query_registry_for_matches_multi(
                reg_urls, timeout=deadline,
                filters=active_filters or None, auth=reg_auth,
            )
        except RuntimeError as exc:
            typer.secho(f"Registry query failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        if not matches:
            typer.secho(
                "No listings matched. " + (
                    f"Filters applied: {active_filters}." if active_filters
                    else "Registry returned nothing."
                ),
                err=True, fg=typer.colors.YELLOW,
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

        aggregation_policy = aggregate_by or resolve_config_value(
            toml_path="aggregation.policy",
        ) or None

        config = BuyConfig(
            registry_urls=reg_urls,
            buyer_address=addr,
            buyer_private_key=pk,
            discovery_timeout=deadline,
            indexer_auth=reg_auth,
            aggregation_policy=aggregation_policy,
        )
        constraints = BuyConstraints(
            max_price=max_price,
            initial_price=initial_price,
            policy_params=policy_params_all,
        )
        provision = make_api_tokens_provision_terms(
            quantity=int(quantity),
            key_mode=key_mode,
            key_id=resolved_key_id,
        )

        from core_buyer.escrow_selection import select_escrow_entry

        def build_escrow_proposal_for_match(match: dict) -> EscrowProposal | None:
            entry = select_escrow_entry(
                match,
                chain_name=selected_chain_name,
                token_contract_filter=tc,
                assume_yes=assume_yes,
                rpc_url=rpc,
                buyer_address=addr,
                console=console,
                compatible=configured_buyer_policy().compatible,
            )
            if entry is None:
                return None
            return escrow_proposal_from_accepted_entry(
                listing=match,
                entry=entry,
                expiration_unix=int(time.time()) + int(expiration_seconds),
            )

        run_log = RunLog.start(
            command="market tokens buy",
            buyer_address=addr,
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
            filters=active_filters or None,
            chain_name=selected_chain_name,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        header.add_row("Registries", ", ".join(reg_urls))
        header.add_row("Buyer wallet", addr)
        header.add_row("Quantity", str(quantity))
        header.add_row("Key", key_mode + (f" ({resolved_key_id})" if resolved_key_id else ""))
        header.add_row("Opening bid / ceiling (per token)", f"{initial_price} / {max_price}")
        header.add_row("Max matches", str(max_matches))
        if active_filters:
            header.add_row("Filters", ", ".join(f"{k}={v}" for k, v in active_filters.items()))
        console.print(Panel(header, title="market tokens buy", border_style="cyan"))

        def _observe(stage: str, body: dict) -> None:
            # Append a structured event to the run log so post-mortem
            # inspection and `--from` resume have something to read.
            run_log.event(stage, **body)

            if stage == "discover":
                console.print(f"[dim]discover[/dim]  {body.get('match_count', 0)} match(es)")
            elif stage == "negotiation_started":
                console.print(f"[dim]negotiate →[/dim] {body.get('seller_url')} ({body.get('listing_id')})")
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

        confirm_settlement_cb = None
        if not assume_yes and os.isatty(0):
            def confirm_settlement_cb(terms, listing):  # noqa: E306
                return _confirm_settlement_interactive(
                    terms=terms, listing=listing,
                    quantity=int(quantity), console=console,
                )

        # The chain is always built locally so the API-tokens default
        # guards (answer_key_challenge) ride even with no [negotiation]
        # config — core's own default would use only the shape guard.
        from .common import resolve_negotiation_config
        policies, policy_mode = resolve_negotiation_config()
        negotiation_chain = _load_buyer_chain(
            policies=policies,
            policy_mode=policy_mode,
            default_guards=buyer_policies.APITOKENS_BUYER_GUARDS,
        )

        negotiate_hook = make_negotiate_hook(
            config=config,
            constraints=constraints,
            provision=provision,
            unit_count=float(quantity),
            build_escrow_proposal=build_escrow_proposal_for_match,
            max_negotiation_rounds=max_rounds,
            derive_prices=None,
            chain=negotiation_chain,
        )
        settle_hook = make_settle_hook(
            config=config,
            unit_count=float(quantity),
            duration_seconds=0,  # token deals fund a quantity, not a lease
            ssh_public_key="",
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

    tokens_app.command("buy")(inject_policy_cli_params(buy, _policy))
