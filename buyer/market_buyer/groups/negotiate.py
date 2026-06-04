"""`market negotiate` — buyer-as-client sync negotiation, one deal.

Thin wrapper around buyer_client.negotiate_with_seller(). Demonstrates
the pattern end-to-end: the CLI makes no agent assumptions, runs
entirely as an HTTP client talking to the seller.

Intended as a building block for the full market-buy rewrite; for now,
exists to exercise /negotiate/new + /negotiate/{id} directly.
"""

from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..common import resolve_config_value
from ..buyer_client import ResumeState, negotiate_with_seller
from ..run_log import RunLog
from ._cli_helpers import resolve_prices_from_matches
from ._deal import load_negotiation_resume_point


def register(app: typer.Typer) -> None:
    """Register the top-level `market negotiate` command."""

    @app.command("negotiate")
    def negotiate(
        seller_url: Optional[str] = typer.Option(
            None, "--seller", "-s",
            help="Seller agent base URL. Optional — resolved from the "
                 "registry given --listing-id; resumed runs (--from) "
                 "read it from the run-log. Pass explicitly to override.",
        ),
        listing_id: Optional[str] = typer.Option(
            None, "--listing-id",
            help="The seller's listing_id. Required for fresh runs; "
                 "resumed runs (--from) read it from the run-log.",
        ),
        registry_urls: Optional[str] = typer.Option(
            None, "--registry-urls",
            help="Comma-separated registry base URLs (default: "
                 "registry.urls from config.toml). Used to resolve the "
                 "seller URL and price floor from a listing_id; the "
                 "first registry that knows the listing wins.",
        ),
        discovery_timeout: Optional[float] = typer.Option(
            None, "--discovery-timeout",
            help="Per-registry deadline in seconds (default: "
                 "registry.discovery_timeout from config.toml, fallback 5).",
        ),
        initial_price: Optional[float] = typer.Option(
            None, "--initial-price",
            help="Opening bid in human / whole-token units, per-hour rate. "
                 "Scaled by the token's on-chain decimals before being sent "
                 "(--initial-price 2 against 6-decimal USDC = $2/hr). "
                 "Optional — when omitted, anchored on the listing's advertised min_price.",
        ),
        max_price: Optional[float] = typer.Option(
            None, "--max-price",
            help="Ceiling in human / whole-token units, per-hour rate. "
                 "Scaled by the token's on-chain decimals before being sent. "
                 "Optional — when omitted, derived as min_price * --price-markup. "
                 "Resumed runs reuse the original ceiling.",
        ),
        price_markup: float = typer.Option(
            1.5, "--price-markup",
            help="Multiplier on the listing's min_price for the auto-derived "
                 "--max-price. Ignored when --max-price is explicit.",
        ),
        assume_yes: bool = typer.Option(
            False, "--yes", "-y",
            help="Skip interactive confirmations on auto-derived prices.",
        ),
        max_rounds: int = typer.Option(
            10, "--max-rounds",
            help="Walk away after this many buyer-initiated counters.",
        ),
        from_run: Optional[str] = typer.Option(
            None, "--from",
            help="Resume the round loop of a prior `market negotiate` run "
                 "(by run-id). Skips /negotiate/new; replays the seller's "
                 "last counter into the strategy and continues. Useful "
                 "when the buyer crashed mid-round but the seller's "
                 "thread state is still live.",
        ),
        buyer_address: Optional[str] = typer.Option(
            None, "--buyer-address",
            help="Override buyer wallet address (default: derived from wallet.private_key).",
        ),
        buyer_private_key: Optional[str] = typer.Option(
            None, "--buyer-priv-key",
            help="Override buyer private key (default: wallet.private_key).",
        ),
        duration_hours: Optional[float] = typer.Option(
            None, "--duration-hours", "-t",
            help="Lease duration the buyer wants (hours, fractional ok). "
                 "Required for fresh runs — sent on /negotiate/new and "
                 "validated server-side against the listing's max_duration_seconds. "
                 "Resumed runs read it from the run-log.",
        ),
        token_contract: Optional[str] = typer.Option(
            None, "--token-contract",
            help="Optional ERC-20 accepted-escrow filter. Omit to use the "
                 "token/escrow shape selected from the listing.",
        ),
        token_decimals: Optional[float] = typer.Option(
            None, "--token-decimals",
            help="ERC-20 token decimals override for scaling price flags. "
                 "Only needed when decimals cannot be resolved on chain.",
        ),
        chain_name: Optional[str] = typer.Option(
            None, "--chain",
            help="Which [chains.<name>] entry to negotiate against. When "
                 "omitted the buyer prompts; required when --yes is set "
                 "and the listing accepts more than one chain you have configured.",
        ),
    ) -> None:
        """Drive a synchronous negotiation with one seller, round-by-round.

        Each round is a signed HTTP POST to the seller. The seller's
        policy decides counter/accept/exit and returns the decision
        inline. The buyer's policy (simple ceiling + midpoint counter)
        runs locally in this process.
        """
        console = Console()

        # Capture which prices the user passed explicitly — auto-derived
        # values (from the listing's advertised min_price) are already
        # in base units and must not be scaled again below.
        _initial_explicit = initial_price is not None
        _max_explicit = max_price is not None

        # Resolution: CLI flag > config.toml > derivation.
        from ..common import resolve_buyer_wallet
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

        resume_state = None
        if from_run:
            resume_point = load_negotiation_resume_point(from_run)
            seller_url = seller_url or resume_point.seller_url
            listing_id = listing_id or resume_point.listing_id
            if max_price is None:
                typer.secho(
                    "--max-price is required when resuming (the strategy "
                    "needs the buyer's ceiling).",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            resume_state = ResumeState(
                negotiation_id=resume_point.negotiation_id,
                transcript=resume_point.transcript,
                last_seller_proposal=resume_point.last_seller_proposal,
                rounds_completed=resume_point.rounds_completed,
            )

        # Resolve registry URLs + per-registry deadline + auth once.
        from ..common import (
            resolve_indexer_urls, resolve_discovery_timeout, resolve_indexer_auth,
        )
        reg_urls = resolve_indexer_urls(override=registry_urls)
        deadline = resolve_discovery_timeout(override=discovery_timeout)
        reg_auth = resolve_indexer_auth()

        # Fetch the listing — needed for both --seller auto-resolution
        # and picking an accepted_escrows entry. Skipped in resume mode
        # (the saved run-log carries the prior commitments).
        listing_dict: Optional[dict] = None
        if listing_id and resume_state is None:
            from ..buy_orchestrator import fetch_listing_dict_multi
            try:
                listing_dict = fetch_listing_dict_multi(
                    reg_urls, listing_id, timeout=deadline, auth=reg_auth,
                )
            except RuntimeError as exc:
                typer.secho(
                    f"Could not fetch listing {listing_id}: {exc}",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            if not listing_dict:
                typer.secho(
                    f"No listing {listing_id!r} in any of "
                    f"{len(reg_urls)} registries.",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            if not seller_url:
                seller_url = listing_dict.get("seller")
                if not seller_url:
                    typer.secho(
                        f"Listing {listing_id} has no `seller` field; pass --seller explicitly.",
                        err=True, fg=typer.colors.RED,
                    )
                    raise typer.Exit(2)
            # Auto-derive prices from the listing's min_price when caller
            # didn't supply them. Same precedent as `market buy`.
            if initial_price is None or max_price is None:
                derived_initial, derived_max = resolve_prices_from_matches(
                    matches=[listing_dict],
                    console=console,
                    assume_yes=assume_yes,
                    price_markup=price_markup,
                )
                if derived_initial is None or derived_max is None:
                    raise typer.Exit(2)
                initial_price = initial_price if initial_price is not None else derived_initial
                max_price = max_price if max_price is not None else derived_max

        if not seller_url or not listing_id:
            typer.secho(
                "Missing required negotiation inputs. For a fresh run pass "
                "--listing-id (and optionally --seller); for a resume pass --from <run-id>.",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)

        if resume_state is None and (initial_price is None or max_price is None):
            typer.secho(
                "Fresh runs require --initial-price and --max-price (or a "
                "registry-discoverable listing_id with an advertised min_price).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        if resume_state is None and (duration_hours is None or duration_hours <= 0):
            typer.secho(
                "Fresh runs require --duration-hours (the buyer's lease ask).",
                err=True, fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        duration_seconds = (
            int(round(duration_hours * 3600)) if duration_hours is not None else None
        )

        # Pick one accepted_escrows entry — token, escrow contract, and
        # chain all come from the listing. ``--token-contract`` (when
        # set) filters entries to one ERC-20.
        from ..escrow_selection import select_escrow_entry
        from ..common import select_chain_for_listing
        picked_entry: Optional[dict] = None
        chain_cfg = None
        if listing_dict is not None:
            chain_cfg = select_chain_for_listing(
                listing=listing_dict, override=chain_name, yes=assume_yes,
            )
            picked_entry = select_escrow_entry(
                listing_dict,
                chain_name=chain_cfg.name,
                token_contract_filter=token_contract,
                assume_yes=assume_yes,
                rpc_url=chain_cfg.rpc_url,
                buyer_address=addr,
                console=console,
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
            from service.schemas import accepted_token_address
            entry_token = accepted_token_address(picked_entry)
            if isinstance(entry_token, str) and entry_token.startswith("0x"):
                # Surface the picked token back to the run-log + the
                # downstream price-scaling step.
                token_contract = entry_token

        # Scale explicit --initial-price / --max-price from human /
        # whole-token units to base units. Sellers publish
        # ``price_per_hour`` in base units; buyer ceilings need the
        # same scale to compare apples-to-apples. Use --token-decimals
        # when supplied, otherwise resolve via on-chain ``decimals()``.
        if _initial_explicit or _max_explicit:
            decimals: Optional[int] = (
                int(token_decimals) if token_decimals is not None else None
            )
            if decimals is None:
                from service.clients.token import (
                    resolve_token, TokenResolutionError,
                )
                tc = token_contract
                if tc and chain_cfg is not None:
                    try:
                        meta = resolve_token(
                            tc, rpc_url=chain_cfg.rpc_url, chain_id=chain_cfg.chain_id,
                        )
                        decimals = meta.decimals
                    except (TokenResolutionError, RuntimeError):
                        decimals = None
            if decimals is None:
                typer.secho(
                    "Could not resolve token decimals to scale prices. "
                    "Pass --token-decimals or ensure the listing's accepted "
                    "chain is configured in [chains.<name>].",
                    err=True, fg=typer.colors.RED,
                )
                raise typer.Exit(2)
            scale = 10 ** int(decimals)
            if _initial_explicit and initial_price is not None:
                initial_price = initial_price * scale
            if _max_explicit and max_price is not None:
                max_price = max_price * scale

        seller_wallet: Optional[str] = None

        run_log = RunLog.start(
            command="market negotiate",
            seller_url=seller_url,
            listing_id=listing_id,
            buyer_address=addr,
            initial_price=initial_price,
            max_price=max_price,
            max_rounds=max_rounds,
            seller_wallet_address=seller_wallet,
            duration_seconds=duration_seconds,
            token_contract=token_contract,
            token_decimals=token_decimals,
            resumed_from=from_run,
            chain_name=(chain_cfg.name if chain_cfg is not None else None),
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
        from service.schemas import EscrowProposal, ProvisionTerms
        import time as _time
        provision_terms: Optional[ProvisionTerms] = None
        escrow_proposal: Optional[EscrowProposal] = None
        if resume_state is None:
            assert duration_seconds is not None  # gated above
            assert picked_entry is not None  # listing fetched + entry picked above
            provision_terms = ProvisionTerms(
                duration_seconds=int(duration_seconds),
                ssh_public_key="",  # negotiate-only flow; settle is a separate command
            )
            from service.schemas import accepted_demands, accepted_token_address
            literal_fields = dict(picked_entry.get("literal_fields") or {})
            _entry_token = accepted_token_address(picked_entry)
            if _entry_token:
                literal_fields["token"] = _entry_token
            selected_chain = picked_entry.get("chain_name")
            demands = [
                d for d in accepted_demands(listing_dict or {})
                if not d.get("chain_name") or d.get("chain_name") == selected_chain
            ]
            escrow_proposal = EscrowProposal(
                chain_name=selected_chain,
                escrow_address=picked_entry["escrow_address"],
                fields={"token": _entry_token},
                literal_fields=literal_fields,
                demands=demands,
                expiration_unix=int(_time.time()) + 3600,
            )

        # Honor optional [negotiation] policies / policy_mode overrides
        # in buyer.toml, mirroring the seller's [negotiation] knob.
        # `policies` is the explicit ordered list; `policy_mode` is the
        # legacy single-terminal key. The buyer wheel installs without
        # torch by default — set "bisection" to avoid the RL self-register
        # path blowing up. When both are unset, negotiate_with_seller
        # falls through to its default chain.
        chain = None
        from ..common import resolve_negotiation_config
        policies, policy_mode = resolve_negotiation_config()
        if policies or policy_mode:
            from market_buyer.buyer_client import _load_buyer_chain
            chain = _load_buyer_chain(policies=policies, policy_mode=policy_mode)

        try:
            outcome = negotiate_with_seller(
                seller_url=seller_url,
                buyer_address=addr,
                buyer_private_key=pk,
                listing_id=listing_id,
                initial_price=initial_price or 0,
                max_price=max_price,
                provision_terms=provision_terms,
                escrow_proposal=escrow_proposal,
                max_rounds=max_rounds,
                on_round=_observe,
                resume=resume_state,
                chain=chain,
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
