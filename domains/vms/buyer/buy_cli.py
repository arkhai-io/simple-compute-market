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
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from domains.vms.listings import build_vm_filter_params
from domains.vms.provisioning import make_vm_provision_terms
from domains.vms.settlement import escrow_proposal_from_accepted_entry
from market_alkahest.schemas import EscrowProposal

from .buy_orchestrator import (
    BuyConfig,
    BuyConstraints,
    extract_seller_min_price,
    make_legacy_negotiate_hook,
    make_legacy_settle_hook,
    query_registry_for_matches_multi,
    run_buy,
)
from .buyer_client import ResumeState, negotiate_with_seller
from .common import resolve_config_value
from .deal_helpers import (
    is_negotiation_complete,
    load_negotiation_resume_point,
    open_run_log,
)
from .settle_cli import run_settle_from_log
from .run_log import RunLog


def _confirm_settlement_interactive(*, terms, listing: dict, console: Console) -> bool:
    """Prompt the buyer to approve settlement at the negotiated price.

    Shown after negotiation agrees but BEFORE create_escrow runs — i.e.,
    no on-chain transaction has been emitted and the seller's /settle
    endpoint hasn't been touched yet. Declining here is a clean exit.

    Displays the agreed per-hour rate, duration, total payment (= rate
    × duration_seconds / 3600), seller URL, and listing ID so the buyer
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
        return typer.confirm("Proceed to settlement (escrow + /settle + poll)?", default=True)
    except typer.Abort:
        return False


from .cli_helpers import resolve_prices_from_matches as _resolve_prices_from_matches  # noqa: E402,F401


def _run_resume_from(
    *,
    from_run: str,
    max_price: Optional[float],
    buyer_address: Optional[str],
    buyer_private_key: Optional[str],
    ssh_public_key: Optional[str],
    token_contract: Optional[str],
    token_decimals: Optional[int],
    chain_name: Optional[str],
    expiration_seconds: int,
    max_rounds: int,
    poll_interval: float,
    settlement_timeout: float,
    console: Console,
) -> None:
    """Composite resume: finish negotiation if mid-stream, then settle.

    The same run-log is appended throughout — fresh `negotiate`-style
    events when finishing the negotiation, then `settle_*` events from
    ``run_settle_from_log``.
    """
    if not is_negotiation_complete(from_run):
        if max_price is None:
            typer.secho(
                "--max-price is required when resuming a mid-stream "
                "negotiation (the strategy needs the buyer's ceiling).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        from .common import resolve_buyer_wallet
        addr, pk = resolve_buyer_wallet(
            override_addr=buyer_address, override_pk=buyer_private_key,
        )
        if not addr or not pk:
            typer.secho(
                "Missing buyer wallet config. Pass --buyer-priv-key or set "
                "wallet.private_key in config.toml; the address is derived "
                "from the key.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        # Scale --max-price from human / whole-token units to base units.
        # Sellers publish ``price_per_hour`` already in base units, so a
        # buyer ceiling of "2" against 6-decimal USDC means $2/hr → 2_000_000.
        # Resolve token_decimals via the user override or on-chain decimals().
        if token_decimals is None and token_contract:
            # When the buyer's resuming mid-stream, the chain hasn't been
            # selected yet. Use the chain pulled from the run-log via
            # _chain_name_from_run_log; falls back to skipping decimals
            # if the chain isn't yet known.
            from market_alkahest.token import resolve_token, TokenResolutionError
            from .common import chain_by_name
            from .settle_cli import _chain_name_from_run_log
            cname = chain_name or _chain_name_from_run_log(from_run)
            if cname:
                try:
                    chain_cfg = chain_by_name(cname)
                    meta = resolve_token(
                        token_contract,
                        rpc_url=chain_cfg.rpc_url,
                        chain_id=chain_cfg.chain_id,
                    )
                    token_decimals = meta.decimals
                except (TokenResolutionError, RuntimeError):
                    token_decimals = None
        if token_decimals is not None:
            max_price = max_price * (10 ** int(token_decimals))

        resume_point = load_negotiation_resume_point(from_run)
        run_log = open_run_log(from_run)
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
        header.add_row("Ceiling", str(max_price))
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
            from .buyer_client import _load_buyer_chain
            resume_chain = _load_buyer_chain(
                policy_mode=str(resume_point.policy),
            )
        try:
            outcome = negotiate_with_seller(
                seller_url=resume_point.seller_url,
                buyer_address=addr,
                buyer_private_key=pk,
                listing_id=resume_point.listing_id,
                initial_price=0,
                max_price=max_price,
                max_rounds=max_rounds,
                chain=resume_chain,
                on_round=_observe,
                resume=ResumeState(
                    negotiation_id=resume_point.negotiation_id,
                    transcript=resume_point.transcript,
                    last_seller_proposal=resume_point.last_seller_proposal,
                    rounds_completed=resume_point.rounds_completed,
                ),
            )
        except RuntimeError as exc:
            run_log.event("negotiation_failed", error=str(exc))
            run_log.end("error", error=str(exc))
            typer.secho(f"Resumed negotiation failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

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
                err=True, fg=getattr(typer.colors, color.upper(), typer.colors.YELLOW),
            )
            raise typer.Exit(4)

        console.print(
            f"[green]negotiation agreed[/green]  price={outcome.agreed_amount} "
            f"rounds={outcome.rounds}"
        )

    run_settle_from_log(
        run_id=from_run,
        escrow_uid=None,
        token_contract=token_contract,
        token_decimals=token_decimals,
        duration_seconds=None,
        expiration_seconds=expiration_seconds,
        ssh_public_key=ssh_public_key,
        buyer_address=buyer_address,
        buyer_private_key=buyer_private_key,
        chain_name=chain_name,
        poll_interval=poll_interval,
        settlement_timeout=settlement_timeout,
        console=console,
    )


def register(app: typer.Typer) -> None:
    """Register the top-level `market buy` command.

    Pricing flags are not defined here: the configured negotiation
    policy contributes its own parameter surface at app-assembly time
    (design-negotiation-policy-surface.md) — the scalar policies
    contribute --initial-price/--max-price/--price-markup, so the
    default surface is unchanged; a different policy contributes
    different knobs, plus the --policy-param escape hatch.
    """
    from market_policy.buyer_policy import inject_policy_cli_params

    from .policy_surface import configured_buyer_policy

    _policy = configured_buyer_policy()

    def buy(  # registered below after policy-param injection
        assume_yes: bool = typer.Option(
            False, "--yes", "-y",
            help="Skip ALL interactive prompts (price defaults + "
                 "pre-settlement confirmation). Same effect as running "
                 "without a TTY — defaults are accepted automatically. "
                 "Set this for scripts, CI, or non-interactive runs.",
        ),
        quiet: bool = typer.Option(
            False, "--quiet", "-q",
            help="Condensed output: drop the per-step progress panels and "
                 "print one concise summary (deal, escrow, VM, connection) "
                 "when the buy settles. Provisioning shows a simple progress "
                 "line. Good for scripts and clean terminals.",
        ),
        duration_hours: Optional[float] = typer.Option(
            None, "--duration-hours", "-t",
            help="Lease duration the buyer wants (hours, fractional ok). "
                 "Required for fresh runs — sent to the seller's "
                 "/negotiate/new and validated against the listing's "
                 "max_duration_seconds. Resumed runs read it from the run-log.",
        ),
        # Spec filters — slice fields
        gpu_model: Optional[str] = typer.Option(None, "--gpu-model", help="Filter listings by GPU model (e.g., H200)."),
        gpu_count_min: Optional[float] = typer.Option(None, "--gpu-count-min", help="Minimum slice GPU count."),
        vcpu_count_min: Optional[float] = typer.Option(None, "--vcpu-min", help="Minimum slice vCPU count."),
        ram_gb_min: Optional[float] = typer.Option(None, "--ram-gb-min", help="Minimum slice RAM (GB)."),
        disk_gb_min: Optional[float] = typer.Option(None, "--disk-gb-min", help="Minimum slice disk (GB)."),
        region: Optional[str] = typer.Option(None, "--region", help="Filter by region."),
        virtualization_type: Optional[str] = typer.Option(
            None, "--virt", help="Virtualization mode (bare_metal|vm|container).",
        ),
        # Spec filters — host context
        cpu_type: Optional[str] = typer.Option(None, "--cpu-type", help="Filter by host CPU model string."),
        host_cpu_cores_min: Optional[float] = typer.Option(None, "--host-cores-min", help="Minimum host CPU cores."),
        host_ram_gb_min: Optional[float] = typer.Option(None, "--host-ram-gb-min", help="Minimum host RAM (GB)."),
        gpu_interconnect: Optional[str] = typer.Option(
            None, "--interconnect", help="GPU interconnect (nvlink|nvswitch|pcie_only|infiniband).",
        ),
        datacenter_grade: Optional[bool] = typer.Option(
            None, "--datacenter/--no-datacenter", help="Restrict to datacenter-grade hosts.",
        ),
        static_ip: Optional[bool] = typer.Option(
            None, "--static-ip/--no-static-ip", help="Restrict to hosts with static public IP.",
        ),
        raw_filters: Optional[list[str]] = typer.Option(
            None, "--filter", "-f",
            help="Registry filter-spec parameter as name=value. Repeatable. "
                 "Use this for schema-specific filters that do not have a "
                 "compute convenience flag.",
        ),
        from_run: Optional[str] = typer.Option(
            None, "--from",
            help="Resume a partial buy run-id end-to-end. Continues "
                 "negotiation if it stopped mid-stream, then drives "
                 "escrow.create + /settle + poll. The same run-log is "
                 "appended to so `market logs show <id>` captures the "
                 "full lifecycle.",
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
                 "escrow uses this ERC-20. Omit to accept whatever token the "
                 "seller's listing offers on your chain (the token, escrow "
                 "contract, and chain all come from the chosen listing).",
        ),
        token_decimals: Optional[int] = typer.Option(
            None, "--token-decimals",
            help="ERC-20 token decimals override. When omitted, decimals "
                 "are resolved on chain via the token contract's "
                 "decimals() view (and cached at "
                 "$XDG_CACHE_HOME/arkhai/tokens/<chain_id>.json). "
                 "Pass this only when you want to skip the RPC lookup.",
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
            help="How many matching seller orders to try before giving up.",
        ),
        aggregate_by: Optional[str] = typer.Option(
            None, "--aggregate-by",
            help="Across-seller aggregation policy. Default: "
                 "[aggregation].policy from buyer.toml, falling "
                 "back to 'best_price'. Built-ins: best_price, "
                 "fastest_agreed, cheapest_first, registry_order, "
                 "random_shuffle, priceless_last.",
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
            help="Max seconds to wait for provisioning before giving up.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet address (default: derived from wallet.private_key).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        ssh_public_key: Optional[str] = typer.Option(
            None, "--ssh-public-key",
            help="SSH public key for provisioning (default: wallet.ssh_public_key).",
        ),
        **policy_values: Any,
    ) -> None:
        """Run a buy end-to-end as a pure HTTP/web3 client.

        No buyer agent is started or consulted; every step is either a
        signed HTTP call to a seller, a registry query, or a direct
        on-chain call.

        When ``--from <run_id>`` is supplied, picks up wherever the
        prior run left off: finishes the negotiation if it stopped
        mid-stream, then drives stages 3-5 (escrow → submit → poll).
        """
        console = Console()

        from .cli_helpers import parse_filter_options

        # The configured policy's parameters arrive through the injected
        # flags; the scalar policies' names are unpacked for the body.
        initial_price: Optional[float] = policy_values.get("initial_price")
        max_price: Optional[float] = policy_values.get("max_price")
        price_markup: float = float(policy_values.get("price_markup") or 1.5)
        extra_policy_params = parse_filter_options(
            policy_values.get("policy_param") or [],
        )

        if from_run:
            _run_resume_from(
                from_run=from_run,
                max_price=max_price,
                buyer_address=buyer_address,
                buyer_private_key=buyer_private_key,
                ssh_public_key=ssh_public_key,
                token_contract=token_contract,
                token_decimals=token_decimals,
                chain_name=chain_name,
                expiration_seconds=expiration_seconds,
                max_rounds=max_rounds,
                poll_interval=poll_interval,
                settlement_timeout=settlement_timeout,
                console=console,
            )
            return

        if duration_hours is None or duration_hours <= 0:
            typer.secho(
                "Fresh `market buy` runs require --duration-hours "
                "(the buyer's lease ask).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        duration_seconds = int(round(duration_hours * 3600))

        explicit_prices = initial_price is not None and max_price is not None
        if not explicit_prices and (initial_price is not None) != (max_price is not None):
            typer.secho(
                "Pass both --initial-price and --max-price, or neither "
                "(in which case prices are derived from seller min_price).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if price_markup <= 0:
            typer.secho("--price-markup must be positive.", err=True, fg=typer.colors.RED)
            raise typer.Exit(2)

        # Resolution: CLI flag > config.toml > derivation > default.
        from .common import (
            resolve_buyer_wallet,
            resolve_ssh_public_key, resolve_indexer_urls,
            resolve_discovery_timeout, resolve_indexer_auth,
            select_chain_for_listing,
        )
        addr, pk = resolve_buyer_wallet(
            override_addr=buyer_address, override_pk=buyer_private_key,
        )
        ssh = resolve_ssh_public_key(override=ssh_public_key)
        reg_urls = resolve_indexer_urls(override=registry_urls)
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
            "ssh_public_key": "wallet.ssh_public_key",
            "registry_urls": "registry.urls",
        }
        missing = [n for n, v in (
            ("buyer_priv_key", pk),
            ("ssh_public_key", ssh), ("registry_urls", reg_urls),
        ) if not v]
        if missing:
            typer.secho("Missing required config:", err=True, fg=typer.colors.RED)
            for name in missing:
                typer.secho(
                    f"  • {name} — set with: market config set {_key_for[name]} <value>",
                    err=True, fg=typer.colors.RED,
                )
            typer.secho(
                "Run `market config init-user` to scaffold a config file with the full set of keys.",
                err=True, fg=typer.colors.YELLOW,
            )
            raise typer.Exit(2)

        # --token-contract acts as a filter on each candidate listing's
        # accepted_escrows. Without it, listings on the buyer's chain
        # using any token are eligible — but explicit --initial-price /
        # --max-price would be ambiguous (which token's decimals to scale
        # by?), so we require it when those are set.
        tc = token_contract
        if explicit_prices and not tc:
            typer.secho(
                "--initial-price and --max-price require --token-contract "
                "so prices can be scaled to the right decimals. Without it, "
                "drop the explicit price flags and let prices anchor on each "
                "listing's advertised price_per_hour.",
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

        # Build the escrow-terms builder + on-chain submit hook. The
        # builder materializes the negotiation outcome into EscrowTerms
        # (today: one buyer-made ERC20 escrow); the hook submits each
        # buyer-made entry on-chain. Both are env-config-closed at this
        # layer so the orchestrator doesn't see chain creds.
        from domains.vms.settlement import (
            make_buyer_payment_escrow_terms_fn,
            make_create_escrow_fn,
        )
        # Token + expiration come from the proposal (echoed by the seller).
        # The closure only needs chain config to resolve on-chain addresses.
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

        # Filter-aware discovery: pre-fetch matches with spec filters applied
        # so we can (a) show them to the user in interactive mode, (b) anchor
        # auto-price derivation on each listing's seller-advertised min_price.
        active_filters = build_vm_filter_params(
            gpu_model=gpu_model,
            gpu_count_min=gpu_count_min,
            vcpu_count_min=vcpu_count_min,
            ram_gb_min=ram_gb_min,
            disk_gb_min=disk_gb_min,
            region=region,
            virtualization_type=virtualization_type,
            cpu_type=cpu_type,
            host_cpu_cores_min=host_cpu_cores_min,
            host_ram_gb_min=host_ram_gb_min,
            gpu_interconnect=gpu_interconnect,
            datacenter_grade=datacenter_grade,
            static_ip=static_ip,
        )
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
        # explicitly, both anchor on the cheapest advertised rate — open
        # there, bound there (no markup headroom; the default policy
        # never counters).
        if not explicit_prices:
            initial_price, max_price = _resolve_prices_from_matches(
                matches=matches,
                console=console,
                price_markup=price_markup,
            )
            if initial_price is None or max_price is None:
                # No listing carried an advertised price.
                raise typer.Exit(2)

        # Resolve aggregation policy: --aggregate-by > [aggregation].policy > default.
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
            policy_params=extra_policy_params,
        )
        provision = make_vm_provision_terms(
            duration_seconds=duration_seconds,
            ssh_public_key=ssh,
        )
        # Per-candidate escrow proposal: every matched listing carries
        # its own accepted_escrows entries (chain, escrow contract, token,
        # advertised price). The closure runs once per candidate inside
        # the aggregation loop and picks one entry — multi-token listings
        # prompt the user (interactive) or auto-pick by ERC20 balance
        # (--yes). Returning None skips the candidate when no entry is
        # on the buyer's chain or matches --token-contract.
        from domains.vms.settlement import select_escrow_entry

        from .policy_surface import (
            configured_buyer_policy as _configured_buyer_policy,
        )

        def build_escrow_proposal_for_match(match: dict) -> EscrowProposal | None:
            entry = select_escrow_entry(
                match,
                chain_name=selected_chain_name,
                token_contract_filter=tc,
                assume_yes=assume_yes,
                rpc_url=rpc,
                buyer_address=addr,
                console=console,
                compatible=_configured_buyer_policy().compatible,
            )
            if entry is None:
                return None
            return escrow_proposal_from_accepted_entry(
                listing=match,
                entry=entry,
                expiration_unix=int(time.time()) + int(expiration_seconds),
            )

        run_log = RunLog.start(
            command="market buy",
            buyer_address=addr,
            registry_urls=reg_urls,
            policy=_policy.name,
            policy_params=extra_policy_params,
            initial_price=initial_price,
            max_price=max_price,
            duration_seconds=duration_seconds,
            max_matches=max_matches,
            max_rounds=max_rounds,
            filters=active_filters or None,
        )

        header = Table.grid(padding=(0, 2))
        header.add_column(style="bold")
        header.add_column()
        header.add_row("Run ID", run_log.run_id)
        header.add_row("Registries", ", ".join(reg_urls))
        header.add_row("Buyer wallet", addr)
        header.add_row("Opening bid / ceiling", f"{initial_price} / {max_price}")
        header.add_row("Max matches", str(max_matches))
        if active_filters:
            header.add_row("Filters", ", ".join(f"{k}={v}" for k, v in active_filters.items()))
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
                console.print(f"[dim]discover[/dim]  {body.get('match_count', 0)} match(es)")
            elif stage == "negotiation_started":
                console.print(f"[dim]negotiate →[/dim] {body.get('seller_url')} ({body.get('listing_id')})")
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

        confirm_settlement_cb = None
        if not assume_yes and os.isatty(0):
            def confirm_settlement_cb(terms, listing):  # noqa: E306
                return _confirm_settlement_interactive(
                    terms=terms, listing=listing, console=console,
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
            from .buyer_client import _load_buyer_chain
            negotiation_chain = _load_buyer_chain(policies=policies, policy_mode=policy_mode)

        negotiate_hook = make_legacy_negotiate_hook(
            config=config,
            constraints=constraints,
            provision=provision,
            build_escrow_proposal=build_escrow_proposal_for_match,
            max_negotiation_rounds=max_rounds,
            derive_prices=None,
            chain=negotiation_chain,
        )
        settle_hook = make_legacy_settle_hook(
            config=config,
            provision=provision,
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

    app.command("buy")(inject_policy_cli_params(buy, _policy))
