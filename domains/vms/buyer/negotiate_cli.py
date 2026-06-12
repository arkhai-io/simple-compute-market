"""`market negotiate` — buyer-as-client sync negotiation, one deal.

Thin wrapper around buyer_client.negotiate_with_seller(). Demonstrates
the pattern end-to-end: the CLI makes no agent assumptions, runs
entirely as an HTTP client talking to the seller.

Intended as a building block for the full market-buy rewrite; for now,
exists to exercise /negotiate/new + /negotiate/{id} directly.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .buyer_client import ResumeState, negotiate_with_seller
from .common import resolve_config_value
from .cli_helpers import resolve_prices_from_matches
from .deal_helpers import load_negotiation_resume_point
from .run_log import RunLog


def register(app: typer.Typer) -> None:
    """Register the top-level `market negotiate` command.

    Pricing flags come from the configured negotiation policy
    (ARCHITECTURE.md, "Buyer negotiation policy surface"), injected at app assembly —
    the scalar policies contribute --initial-price/--max-price/
    --price-markup, plus the --policy-param escape hatch.
    """
    from market_policy.buyer_policy import inject_policy_cli_params

    from .policy_surface import configured_buyer_policy

    _policy = configured_buyer_policy()

    def negotiate(  # registered below after policy-param injection
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
        **policy_values: Any,
    ) -> None:
        """Drive a synchronous negotiation with one seller, round-by-round.

        Each round is a signed HTTP POST to the seller. The seller's
        policy decides counter/accept/exit and returns the decision
        inline. The buyer's policy decides locally in this process
        (default: listed_price — pay what's published).
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

        # Capture which prices the user passed explicitly — auto-derived
        # values (from the listing's advertised min_price) are already
        # in base units and must not be scaled again below.
        _initial_explicit = initial_price is not None
        _max_explicit = max_price is not None

        # Resolution: CLI flag > config.toml > derivation.
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
        from .common import (
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
            from .buy_orchestrator import fetch_listing_dict_multi
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
        from domains.vms.settlement import select_escrow_entry
        from .common import select_chain_for_listing
        picked_entry: Optional[dict] = None
        chain_cfg = None
        if listing_dict is not None:
            chain_cfg = select_chain_for_listing(
                listing=listing_dict, override=chain_name, yes=assume_yes,
            )
            from .policy_surface import configured_buyer_policy

            picked_entry = select_escrow_entry(
                listing_dict,
                chain_name=chain_cfg.name,
                token_contract_filter=token_contract,
                assume_yes=assume_yes,
                rpc_url=chain_cfg.rpc_url,
                buyer_address=addr,
                console=console,
                compatible=configured_buyer_policy().compatible,
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
                from market_alkahest.token import (
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
            policy=_policy.name,
            policy_params=policy_params_all,
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
        from market_alkahest.schemas import EscrowProposal
        from domains.vms.provisioning.terms import VmProvisionTerms
        from domains.vms.provisioning import make_vm_provision_terms
        from domains.vms.settlement import escrow_proposal_from_accepted_entry
        import time as _time
        provision_terms: Optional[VmProvisionTerms] = None
        escrow_proposal: Optional[EscrowProposal] = None
        if resume_state is None:
            assert duration_seconds is not None  # gated above
            assert picked_entry is not None  # listing fetched + entry picked above
            provision_terms = make_vm_provision_terms(
                duration_seconds=int(duration_seconds),
                ssh_public_key="",  # negotiate-only flow; settle is a separate command
            )
            escrow_proposal = escrow_proposal_from_accepted_entry(
                listing=listing_dict or {},
                entry=picked_entry,
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
            from .buyer_client import _load_buyer_chain
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
                policy_params=policy_params_all,
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
            result_table.add_row("Agreed price", str(outcome.agreed_amount))
        if outcome.reason:
            result_table.add_row("Reason", outcome.reason)
        result_table.add_row("Rounds", str(outcome.rounds))

        border = "green" if outcome.status == "agreed" else "yellow"
        console.print(Panel(result_table, title="Outcome", border_style=border))

        if outcome.status != "agreed":
            raise typer.Exit(4)

    app.command("negotiate")(inject_policy_cli_params(negotiate, _policy))
