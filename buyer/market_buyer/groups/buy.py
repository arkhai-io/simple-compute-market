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
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from service.schemas import EscrowProposal, ProvisionTerms

from ..buy_orchestrator import (
    BuyConfig,
    BuyConstraints,
    extract_seller_min_price,
    query_registry_for_matches_multi,
    run_buy,
)
from ..buyer_client import ResumeState, negotiate_with_seller
from ..common import resolve_config_value
from ..run_log import RunLog
from ._deal import (
    is_negotiation_complete,
    load_negotiation_resume_point,
    open_run_log,
)
from .settle import run_settle_from_log


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
    total = terms.agreed_price * terms.duration_seconds // 3600
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Seller", str(terms.seller_url))
    table.add_row("Listing", str(terms.listing_id))
    table.add_row("Negotiation", str(terms.negotiation_id))
    table.add_row("Agreed price", f"{terms.agreed_price} (per hour, raw token units)")
    table.add_row("Duration", f"{terms.duration_seconds}s ({duration_hours:.4g}h)")
    table.add_row("Total payment", f"{total} (raw token units)")
    console.print(Panel(table, title="Confirm settlement", border_style="yellow"))
    try:
        return typer.confirm("Proceed to settlement (escrow + /settle + poll)?", default=True)
    except typer.Abort:
        return False


from ._cli_helpers import resolve_prices_from_matches as _resolve_prices_from_matches  # noqa: E402,F401


def _run_resume_from(
    *,
    from_run: str,
    max_price: Optional[float],
    buyer_address: Optional[str],
    buyer_private_key: Optional[str],
    ssh_public_key: Optional[str],
    token_contract: Optional[str],
    token_decimals: int,
    rpc_url: Optional[str],
    chain_name: Optional[str],
    alkahest_addr_config: Optional[str],
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

        addr = resolve_config_value(
            override=buyer_address, toml_path="wallet.address",
        )
        pk = resolve_config_value(
            override=buyer_private_key, toml_path="wallet.private_key",
        )
        if not addr or not pk:
            typer.secho(
                "Missing buyer wallet config. Pass --buyer-address + "
                "--buyer-priv-key or set wallet.address + "
                "wallet.private_key in config.toml.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

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

        try:
            outcome = negotiate_with_seller(
                seller_url=resume_point.seller_url,
                buyer_address=addr,
                buyer_private_key=pk,
                listing_id=resume_point.listing_id,
                initial_price=0,
                max_price=max_price,
                max_rounds=max_rounds,
                on_round=_observe,
                resume=ResumeState(
                    negotiation_id=resume_point.negotiation_id,
                    transcript=resume_point.transcript,
                    last_seller_price=resume_point.last_seller_price,
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
            agreed_price=outcome.agreed_price,
            rounds=outcome.rounds,
            reason=outcome.reason,
            negotiation_id=outcome.negotiation_id,
            listing_id=resume_point.listing_id,
        )

        if outcome.status != "agreed" or outcome.agreed_price is None:
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
            f"[green]negotiation agreed[/green]  price={outcome.agreed_price} "
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
        rpc_url=rpc_url,
        chain_name=chain_name,
        alkahest_addr_config=alkahest_addr_config,
        poll_interval=poll_interval,
        settlement_timeout=settlement_timeout,
        console=console,
    )


def register(app: typer.Typer) -> None:
    """Register the top-level `market buy` command."""

    @app.command("buy")
    def buy(
        initial_price: Optional[float] = typer.Option(
            None, "--initial-price",
            help="Opening bid per negotiation (raw token units, per-hour rate). "
                 "Optional — when omitted, prices are derived from the "
                 "seller's advertised min_price (interactively confirmed "
                 "in TTY runs, derived silently with --yes).",
        ),
        max_price: Optional[float] = typer.Option(
            None, "--max-price",
            help="Ceiling per negotiation (raw token units, per-hour rate). "
                 "Optional — when omitted, derived as min_price × "
                 "--price-markup (interactively confirmed in TTY runs, "
                 "derived silently with --yes).",
        ),
        price_markup: float = typer.Option(
            1.5, "--price-markup",
            help="Multiplier applied to seller min_price when auto-deriving "
                 "max-price. Default 1.5 (50%% headroom).",
        ),
        assume_yes: bool = typer.Option(
            False, "--yes", "-y",
            help="Skip ALL interactive prompts (price defaults + "
                 "pre-settlement confirmation). Same effect as running "
                 "without a TTY — defaults are accepted automatically. "
                 "Set this for scripts, CI, or non-interactive runs.",
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
            help="ERC-20 token contract address used for payment. "
                 "Default: resolve 'MOCK' via the token registry.",
        ),
        token_decimals: int = typer.Option(
            18, "--token-decimals",
            help="ERC-20 token decimals (default 18).",
        ),
        chain_name: Optional[str] = typer.Option(
            None, "--chain-name",
            help="Chain name for alkahest address resolution "
                 "(default: chain.name from config.toml).",
        ),
        alkahest_addr_config: Optional[str] = typer.Option(
            None, "--alkahest-addr-config",
            help="Path to alkahest address config JSON "
                 "(default: chain.alkahest_address_config_path).",
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
                 "[buyer.aggregation].policy from config.toml, falling "
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
            help="Override buyer wallet (default: wallet.address from config.toml).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        ssh_public_key: Optional[str] = typer.Option(
            None, "--ssh-public-key",
            help="SSH public key for provisioning (default: wallet.ssh_public_key).",
        ),
        rpc_url: Optional[str] = typer.Option(
            None, "--rpc-url",
            help="Chain RPC URL (default: chain.rpc_url).",
        ),
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

        if from_run:
            _run_resume_from(
                from_run=from_run,
                max_price=max_price,
                buyer_address=buyer_address,
                buyer_private_key=buyer_private_key,
                ssh_public_key=ssh_public_key,
                token_contract=token_contract,
                token_decimals=token_decimals,
                rpc_url=rpc_url,
                chain_name=chain_name,
                alkahest_addr_config=alkahest_addr_config,
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

        # Resolution: CLI flag > config.toml > default.
        addr = resolve_config_value(
            override=buyer_address, toml_path="wallet.address",
        )
        pk = resolve_config_value(
            override=buyer_private_key, toml_path="wallet.private_key",
        )
        from ..common import (
            resolve_ssh_public_key, resolve_indexer_urls,
            resolve_discovery_timeout, resolve_indexer_auth,
        )
        ssh = resolve_ssh_public_key(override=ssh_public_key)
        reg_urls = resolve_indexer_urls(override=registry_urls)
        deadline = resolve_discovery_timeout(override=discovery_timeout)
        reg_auth = resolve_indexer_auth()
        rpc = resolve_config_value(
            override=rpc_url, toml_path="chain.rpc_url",
        )
        chain = resolve_config_value(
            override=chain_name, toml_path="chain.name",
            default="ethereum_sepolia",
        )
        addr_cfg = resolve_config_value(
            override=alkahest_addr_config,
            toml_path="chain.alkahest_address_config_path",
        )

        _key_for = {
            "buyer_address": "wallet.address",
            "buyer_priv_key": "wallet.private_key",
            "ssh_public_key": "wallet.ssh_public_key",
            "registry_urls": "registry.urls",
            "rpc_url": "chain.rpc_url",
        }
        missing = [n for n, v in (
            ("buyer_address", addr), ("buyer_priv_key", pk),
            ("ssh_public_key", ssh), ("registry_urls", reg_urls),
            ("rpc_url", rpc),
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

        # Resolve token contract if not explicitly given. Deferred import
        # so users without the token registry file can still pass --token-contract.
        tc = token_contract
        if not tc:
            from ..common import resolve_default_token
            symbol = resolve_default_token()
            try:
                from service.clients.token import TOKEN_REGISTRY
                meta = TOKEN_REGISTRY.require(symbol)
                tc = meta.contract_address
                token_decimals = meta.decimals
            except Exception as exc:
                typer.secho(
                    f"Could not resolve default token {symbol!r} — pass "
                    f"--token-contract and --token-decimals, or set "
                    f"[buyer].default_token in config.toml. ({exc})",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)

        # Build the escrow-terms builder + on-chain submit hook. The
        # builder materializes the negotiation outcome into EscrowTerms
        # (today: one buyer-made ERC20 escrow); the hook submits each
        # buyer-made entry on-chain. Both are env-config-closed at this
        # layer so the orchestrator doesn't see chain creds.
        from ..escrow_client import (
            make_buyer_payment_escrow_terms_fn,
            make_create_escrow_fn,
        )
        # Token + expiration come from the proposal (echoed by the seller).
        # The closure only needs chain config to resolve on-chain addresses.
        build_escrow_terms = make_buyer_payment_escrow_terms_fn(
            chain_name=chain,
            addr_config_path=addr_cfg or None,
        )
        create_escrow = make_create_escrow_fn(
            private_key=pk,
            rpc_url=rpc,
            chain_name=chain,
            addr_config_path=addr_cfg or None,
        )

        # Filter-aware discovery: pre-fetch matches with spec filters applied
        # so we can (a) show them to the user in interactive mode, (b) anchor
        # auto-price derivation on each listing's seller-advertised min_price.
        spec_filters = {
            "gpu_model": gpu_model,
            "gpu_count_min": gpu_count_min,
            "vcpu_count_min": vcpu_count_min,
            "ram_gb_min": ram_gb_min,
            "disk_gb_min": disk_gb_min,
            "region": region,
            "virtualization_type": virtualization_type,
            "cpu_type": cpu_type,
            "host_cpu_cores_min": host_cpu_cores_min,
            "host_ram_gb_min": host_ram_gb_min,
            "gpu_interconnect": gpu_interconnect,
            "datacenter_grade": datacenter_grade,
            "static_ip": static_ip,
        }
        active_filters = {k: v for k, v in spec_filters.items() if v is not None}
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

        # Interactive vs auto-price: when the buyer hasn't pinned both prices
        # explicitly, anchor on the seller's advertised min_price per match.
        if not explicit_prices:
            initial_price, max_price = _resolve_prices_from_matches(
                matches=matches,
                console=console,
                assume_yes=assume_yes,
                price_markup=price_markup,
            )
            if initial_price is None or max_price is None:
                # User aborted, or no listing carried a min_price.
                raise typer.Exit(2)

        # Resolve aggregation policy: --aggregate-by > [buyer.aggregation].policy > default.
        aggregation_policy = aggregate_by or resolve_config_value(
            toml_path="buyer.aggregation.policy",
        ) or None

        # Counter policy is config-only — no CLI flag yet. Strict_echo
        # default rejects any seller modification to a buyer-pinned field;
        # operators who want to accept counters set the TOML key.
        counter_policy = resolve_config_value(
            toml_path="buyer.counter_policy.policy",
        ) or None

        config = BuyConfig(
            registry_urls=reg_urls,
            buyer_address=addr,
            buyer_private_key=pk,
            discovery_timeout=deadline,
            indexer_auth=reg_auth,
            aggregation_policy=aggregation_policy,
            counter_policy=counter_policy,
        )
        constraints = BuyConstraints(
            max_price=max_price,
            initial_price=initial_price,
        )
        provision = ProvisionTerms(
            duration_seconds=duration_seconds,
            ssh_public_key=ssh,
        )
        # Buyer's escrow shape proposal — picks the canonical
        # ERC20 non-tierable escrow on the configured chain and fills
        # fields["token"] with the resolved token contract.
        # The seller validates against its listing's accepted_escrows
        # set; today that's the same single shape per listing.
        import time as _time
        from service.clients.alkahest import (
            get_erc20_escrow_obligation_nontierable,
        )
        _escrow_addr = get_erc20_escrow_obligation_nontierable(
            chain, config_path=addr_cfg or None,
        )
        escrow_proposal = EscrowProposal(
            chain_name=chain,
            escrow_address=_escrow_addr,
            fields={"token": tc},
            expiration_unix=int(_time.time()) + int(expiration_seconds),
        )

        run_log = RunLog.start(
            command="market buy",
            buyer_address=addr,
            registry_urls=reg_urls,
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
        console.print(Panel(header, title="market buy-sync", border_style="cyan"))

        def _observe(stage: str, body: dict) -> None:
            # Append a structured event to the run log so post-mortem
            # `market logs` and (eventually) `market buy --resume` have
            # something to read. Negotiation-scoped events carry
            # listing_id (and negotiation_id once round 0 returns) so
            # consumers can group per-negotiation.
            run_log.event(stage, **body)

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
                    f"@ {body.get('agreed_price', '-')}  "
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

        # Honor [buyer.negotiation].policy_mode from config (mirrors
        # `market negotiate`). Without this, the buyer falls through to
        # the RL strategy default, which needs torch — not installed in
        # the lean buyer wheel.
        strategy = None
        policy_mode = resolve_config_value(toml_path="buyer.negotiation.policy_mode")
        if policy_mode:
            from market_policy.negotiation_strategy import load_strategy
            strategy = load_strategy(policy_mode)

        try:
            result = run_buy(
                config=config,
                constraints=constraints,
                provision=provision,
                escrow_proposal=escrow_proposal,
                build_escrow_terms=build_escrow_terms,
                create_escrow=create_escrow,
                matches=matches,
                max_matches_to_try=max_matches,
                max_negotiation_rounds=max_rounds,
                settlement_poll_interval=poll_interval,
                settlement_total_timeout=settlement_timeout,
                on_event=_observe,
                confirm_settlement=confirm_settlement_cb,
                strategy=strategy,
            )
        except RuntimeError as exc:
            run_log.end("error", error=str(exc))
            typer.secho(f"Buy failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(3)

        run_log.end(
            result.status,
            seller_url=result.seller_url,
            negotiation_id=result.negotiation_id,
            agreed_price=result.agreed_price,
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
            ("Agreed price", result.agreed_price),
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
