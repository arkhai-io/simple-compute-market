"""The buyer's Alkahest stage: escrow selection, negotiation pricing, escrow creation, and resumption."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Optional

import typer
from arkhai_api_buying.listing import shorten
from arkhai_api_buying.stages import (
    BuyRequest,
    BuyRun,
    SettlementResume,
    StageOption,
    StageOptions,
)
from core_buyer.buyer_config import resolve_buyer_wallet
from core_buyer.negotiation_client import display_to_base_units
from core_buyer.orchestration import (
    make_escrow_settle_hook,
    submit_settlement_request,
    wait_for_settlement,
)
from core_buyer.run_log import RunLog, read_run
from market_alkahest import ALKAHEST_MECHANISM_ID, create_alkahest_registration
from market_alkahest.plans import escrow_terms_from_settlement_plan
from market_alkahest.proposals import escrow_proposal_from_accepted_entry
from market_alkahest.schemas import (
    EscrowTerms,
    accepted_recipient_address,
    accepted_token_address,
    primary_rate_value,
)
from market_alkahest.token import TokenResolutionError, resolve_token
from market_identity import Signer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from arkhai_api_buying_alkahest.chains import (
    buyer_chains,
    chain_by_name,
    select_chain_for_listing,
)
from arkhai_api_buying_alkahest.escrow_client import (
    AlkahestEscrowCodec,
    accepted_proposal_recipient,
    looks_like_propagation_lag,
    make_alkahest_settlement_payload_fn,
    make_buyer_payment_escrow_terms_fn,
    make_create_escrow_fn,
    resumed_proposal_refusal,
)
from arkhai_api_buying_alkahest.escrow_selection import select_escrow_entry


def _option(command: str, name: str, flags: tuple[str, ...], annotation: Any, help: str) -> StageOption:
    return StageOption(command=command, name=name, flags=flags, annotation=annotation, help=help)


OPTIONS: tuple[StageOption, ...] = (
    _option("buy", "token_contract", ("--token-contract",), Optional[str],
            "Optional filter: only consider listings whose accepted escrow uses this ERC-20. Required when passing explicit --initial-price/--max-price (decimals scaling)."),
    _option("buy", "token_decimals", ("--token-decimals",), Optional[int],
            "ERC-20 token decimals override. When omitted, decimals are resolved on chain via the token contract's decimals() view."),
    _option("buy", "chain_name", ("--chain",), Optional[str],
            "Pick which configured [chains.<name>] entry to operate on. Required when --yes is set and the buyer has more than one chain configured; otherwise the buyer prompts."),
    _option("buy", "evm_address", ("--evm-address",), Optional[str],
            "EVM address required for the selected Alkahest effect."),
    _option("buy", "evm_private_key", ("--evm-private-key",), Optional[str],
            "EVM private key required only to create the Alkahest escrow."),
    _option("negotiate", "evm_address", ("--evm-address",), Optional[str],
            "EVM address used only for chain selection and balance checks."),
    _option("negotiate", "evm_private_key", ("--evm-private-key",), Optional[str],
            "Optional EVM key used only to derive the chain address."),
    _option("negotiate", "token_contract", ("--token-contract",), Optional[str],
            "Optional ERC-20 accepted-escrow filter. Omit to use the token/escrow shape selected from the listing."),
    _option("negotiate", "token_decimals", ("--token-decimals",), Optional[float],
            "ERC-20 token decimals override for scaling price flags. Only needed when decimals cannot be resolved on chain."),
    _option("negotiate", "chain_name", ("--chain",), Optional[str],
            "Which [chains.<name>] entry to negotiate against. When omitted the buyer prompts; required when --yes is set and the listing accepts more than one chain you have configured."),
    _option("settle", "escrow_uid", ("--escrow-uid", "-u"), Optional[str],
            "Skip escrow.create when the on-chain escrow already exists. If absent, the run-log is checked for an `escrow_created` event."),
    _option("settle", "evm_address", ("--evm-address",), Optional[str],
            "EVM address required for the Alkahest settlement effect."),
    _option("settle", "evm_private_key", ("--evm-private-key",), Optional[str],
            "EVM private key required only for Alkahest escrow creation."),
    _option("settle", "chain_name", ("--chain",), Optional[str],
            "Override which configured [chains.<name>] entry to settle on. When omitted, reads chain_name from the accepted proposal or escrow_created event."),
)


def format_accepted_escrows(raw: Any) -> str:
    """Compact per-entry summary: chain, token, per-token rate."""
    entries = raw
    if isinstance(entries, str):
        try:
            entries = json.loads(entries)
        except (ValueError, TypeError):
            return shorten(str(raw), 60)
    if not isinstance(entries, list) or not entries:
        return "-"
    lines = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        token = accepted_token_address(entry) or "-"
        rate = primary_rate_value(entry)
        lines.append(
            f"{entry.get('chain_name', '-')}: {shorten(str(token), 14)}"
            + (f" @ {rate}/token" if rate is not None else " (hidden reserve)")
        )
    return "\n".join(lines) or "-"


def _confirm_settlement_interactive(
    *, terms, listing: dict, quantity: int, console: Console
) -> bool:
    """Prompt before creating the negotiated Alkahest escrow.

    Declining before the on-chain call is a clean exit.
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
            "Proceed to settlement (create Alkahest escrow + poll)?", default=True
        )
    except typer.Abort:
        return False


def _chain_name_from_run_log(run_id: str, *, signer: Signer) -> Optional[str]:
    """Look up the chain the deal targets from signer-bound recovery state."""
    for ev in read_run(run_id, signer=signer):
        if ev.get("event") == "escrow_created":
            cn = ev.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
            terms = ev.get("terms") or {}
            cn = terms.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
        if ev.get("event") == "run_started":
            cn = ev.get("chain_name")
            if isinstance(cn, str) and cn:
                return cn
    return None


def _accepted_proposal_chain(deal) -> Optional[str]:
    terms = getattr(deal, "accepted_escrow_terms", None)
    if isinstance(terms, list) and terms:
        first = terms[0]
        if isinstance(first, dict):
            chain = first.get("chain_name")
            if isinstance(chain, str) and chain:
                return chain
    proposal = getattr(deal, "accepted_escrow_proposal", None)
    if isinstance(proposal, dict):
        chain = proposal.get("chain_name")
        if isinstance(chain, str) and chain:
            return chain
    return None


def _refuse_without_release_condition(log: RunLog, reason: str) -> None:
    """End a settlement that has no accepted release condition to create under.

    The seller settles the escrow only under the release condition it accepted;
    one created under any other would never be released to it, so nothing is
    created.
    """
    error = (
        f"Cannot create the escrow: {reason}. A resumed run creates an escrow "
        "only from the seller's accepted escrow terms recorded in its run-log; "
        "re-run negotiation so they are captured."
    )
    log.event("escrow_release_condition_missing", error=error)
    log.end("error", error=error)
    typer.secho(error, err=True, fg=typer.colors.RED)
    raise typer.Exit(3)


class AlkahestBuySession:
    """The Alkahest part of one buy: the wallet and chain it settles on, and its escrow adapters."""

    def __init__(self, stage: AlkahestBuyerStage, request: BuyRequest) -> None:
        self._stage = stage
        self._request = request
        self._address: str | None = None
        self._private_key: str | None = None
        self._chain: Any = None
        self._build_escrow_terms: Any = None
        self._create_escrow: Any = None

    @property
    def available(self) -> bool:
        return self._chain is not None

    def prepare(self) -> None:
        if not self._request.enabled:
            return
        options = self._request.options
        self._address, self._private_key = self._stage.wallet(
            override_addr=options.get("evm_address"), override_pk=options.get("evm_private_key")
        )
        chains = self._stage.chains()
        if not (self._address and self._private_key and chains):
            return
        chain = select_chain_for_listing(
            listing=None, override=options.get("chain_name"), yes=self._request.assume_yes,
            chains=chains,
        )
        address_config = chain.alkahest_address_config_path or None
        self._build_escrow_terms = make_buyer_payment_escrow_terms_fn(
            chain_name=chain.name, addr_config_path=address_config
        )
        self._create_escrow = make_create_escrow_fn(
            private_key=self._private_key,
            rpc_url=chain.rpc_url,
            chain_name=chain.name,
            addr_config_path=address_config,
        )
        self._chain = chain

    def missing(self) -> tuple[tuple[str, str], ...]:
        missing = []
        if not self._address:
            missing.append(("buyer_evm_address", "wallet.address"))
        if not self._private_key:
            missing.append(("buyer_evm_private_key", "wallet.private_key"))
        if not self._stage.chains():
            missing.append(("chain configuration", "chains.<name>"))
        return tuple(missing)

    def scale_explicit_prices(self, initial: Any, maximum: Any) -> tuple[Any, Any]:
        if not self.available:
            return initial, maximum
        token = self._request.options.get("token_contract")
        if not token:
            typer.secho(
                "--initial-price and --max-price require --token-contract when settling with Alkahest.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        decimals = self._request.options.get("token_decimals")
        if decimals is None:
            try:
                decimals = resolve_token(
                    token, rpc_url=self._chain.rpc_url, chain_id=self._chain.chain_id
                ).decimals
            except (TokenResolutionError, RuntimeError) as exc:
                typer.secho(
                    f"Could not resolve token {token} on chain {self._chain.name!r} — pass --token-decimals or check the chain's rpc_url. ({exc})",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(2)
        try:
            return (
                display_to_base_units(initial, decimals, field="--initial-price"),
                display_to_base_units(maximum, decimals, field="--max-price"),
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    def propose(self, listing: Mapping[str, Any], *, expiration_unix: int) -> Any | None:
        if not self.available:
            return None
        policy = self._request.policy
        entry = select_escrow_entry(
            listing,
            chain_name=self._chain.name,
            token_contract_filter=self._request.options.get("token_contract"),
            assume_yes=self._request.assume_yes,
            rpc_url=self._chain.rpc_url,
            buyer_address=self._address,
            console=self._request.console,
            compatible=policy.compatible,
            preference=policy.prefer_settlement,
        )
        if entry is None:
            return None
        return escrow_proposal_from_accepted_entry(
            listing=listing, entry=entry, expiration_unix=expiration_unix
        )

    def run_fields(self) -> Mapping[str, Any]:
        return {
            "buyer_evm_address": self._address,
            "chain_name": self._chain.name if self._chain is not None else None,
        }

    def header_rows(self) -> tuple[tuple[str, str], ...]:
        return (("EVM chain wallet", self._address),) if self._address else ()

    def settle(self, negotiation: Any, on_event: Any, run: BuyRun) -> Any:
        self._stage.validate_acceptance(negotiation.outcome)
        if not self.available:
            raise ValueError("Alkahest settlement resources are unavailable")
        confirm = None
        if run.interactive:
            console = self._request.console

            def confirm(terms, listing):
                return _confirm_settlement_interactive(
                    terms=terms, listing=listing, quantity=run.quantity, console=console,
                )

        hook = make_escrow_settle_hook(
            config=run.config,
            unit_count=float(run.quantity),
            duration_seconds=0,
            build_escrow_terms=self._build_escrow_terms,
            create_escrow=self._create_escrow,
            settlement_recipient=accepted_proposal_recipient,
            build_settlement_payload=make_alkahest_settlement_payload_fn(
                buyer_evm_address=self._address
            ),
            settlement_submit_max_attempts=6,
            settlement_submit_retryable=looks_like_propagation_lag,
            confirm_settlement=confirm,
            settlement_poll_interval=run.poll_interval,
            settlement_total_timeout=run.settlement_timeout,
            sleep=time.sleep,
        )
        return hook(negotiation, on_event)


class AlkahestBuyerStage:
    """``wallet`` and ``chains`` resolve the buyer's EVM wallet and configured chains; each defaults to the buyer's configuration."""

    mechanism_id = ALKAHEST_MECHANISM_ID
    escrow_codec = AlkahestEscrowCodec()
    options = OPTIONS
    registration = staticmethod(create_alkahest_registration)

    def __init__(
        self,
        *,
        wallet: Callable[..., tuple[str | None, str | None]] | None = None,
        chains: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._wallet = wallet
        self._chains = chains

    def wallet(self, **overrides: Any) -> tuple[str | None, str | None]:
        return (self._wallet or resolve_buyer_wallet)(**overrides)

    def chains(self) -> dict[str, Any]:
        return (self._chains or buyer_chains)()

    def resources(self) -> dict[str, Any]:
        chains = buyer_chains()
        address, _private_key = resolve_buyer_wallet()
        resources = {"chains": chains, "wallet": {"address": address}}
        if len(chains) == 1:
            resources["default_chain"] = next(iter(chains))
        return resources

    def chain_config_paths(self) -> Mapping[str, str | None]:
        return {name: chain.alkahest_address_config_path for name, chain in buyer_chains().items()}

    def negotiation_run_fields(self, options: StageOptions, selected: Any | None) -> Mapping[str, Any]:
        return {
            "token_contract": options.get("token_contract"),
            "token_decimals": options.get("token_decimals"),
            "chain_name": self.accepted_entry(selected).get("chain_name") if selected else None,
        }

    def prepare_selection(
        self, selected: Any, *, listing: Any, settlement_policy: Any, policy: Any,
        options: StageOptions, assume_yes: bool, console: Any,
    ) -> Any:
        token_contract = options.get("token_contract")
        address, _key = resolve_buyer_wallet(
            override_addr=options.get("evm_address"), override_pk=options.get("evm_private_key"),
        )
        if not address:
            raise ValueError(
                "Missing EVM address required to select and inspect the Alkahest "
                "escrow. Pass --evm-address or configure wallet.address."
            )
        candidates = [
            option for _registration, option in settlement_policy.compatible_options(
                listing.get("settlement_options") or (),
            ) if option.mechanism == selected.selection.mechanism
        ]
        constrained = dict(listing)
        constrained["accepted_escrows"] = [self.accepted_entry(
            replace(selected, option=option),
        ) for option in candidates]
        chain = select_chain_for_listing(constrained, override=options.get("chain_name"), yes=assume_yes)
        entry = select_escrow_entry(
            constrained, chain_name=chain.name, token_contract_filter=token_contract,
            assume_yes=assume_yes, rpc_url=chain.rpc_url, buyer_address=address,
            console=console, compatible=policy.compatible,
            preference=policy.prefer_settlement,
        )
        if entry is None:
            message = (
                f"Listing {listing.get('listing_id')!r} has no accepted_escrows entry "
                f"on chain {chain.name!r}"
            )
            if token_contract:
                message += f" with token {token_contract}"
            raise ValueError(message + ".")
        option = next(option for option in candidates if option.params["accepted_escrow"] == entry)
        return replace(selected, option=option, selection=selected.selection.model_copy(
            update={"option_id": option.option_id},
        ))

    def accepted_entry(self, selected: Any) -> dict[str, Any]:
        entry = selected.option.params.get("accepted_escrow")
        if not isinstance(entry, Mapping):
            raise ValueError("selected Alkahest option has no accepted escrow payload")
        return dict(entry)

    def negotiation_prices(
        self, selected: Any, *, initial_price: Any, max_price: Any,
        initial_explicit: bool, max_explicit: bool, options: StageOptions,
    ) -> tuple[Any, Any]:
        token_decimals = options.get("token_decimals")
        if initial_explicit or max_explicit:
            decimals = int(token_decimals) if token_decimals is not None else None
            if decimals is None:
                entry = self.accepted_entry(selected)
                token = accepted_token_address(entry)
                chain = chain_by_name(entry["chain_name"])
                if token and token.startswith("0x"):
                    try:
                        decimals = resolve_token(
                            token, rpc_url=chain.rpc_url, chain_id=chain.chain_id,
                        ).decimals
                    except (TokenResolutionError, RuntimeError):
                        decimals = None
            if decimals is None:
                raise ValueError(
                    "Could not resolve token decimals to scale prices. "
                    "Pass --token-decimals or ensure the listing's accepted "
                    "chain is configured in [chains.<name>]."
                )
            if initial_explicit and initial_price is not None:
                initial_price = display_to_base_units(
                    initial_price, decimals, field="--initial-price"
                )
            if max_explicit and max_price is not None:
                max_price = display_to_base_units(max_price, decimals, field="--max-price")
        return initial_price, max_price

    def proposal(self, listing: Any, selected: Any) -> Any:
        return escrow_proposal_from_accepted_entry(
            listing=listing, entry=self.accepted_entry(selected),
            expiration_unix=selected.selection.expiration_unix,
        )

    def validate_acceptance(self, outcome: Any) -> None:
        if outcome.accepted_escrow_proposal is None:
            raise ValueError("Alkahest acceptance requires the accepted escrow proposal")
        if not outcome.settlement_plan:
            raise ValueError("Alkahest acceptance requires the accepted settlement plan")

    def enrich(self, deal: Any) -> None:
        if deal.accepted_escrow_proposal is not None:
            recipient = accepted_recipient_address(deal.accepted_escrow_proposal)
            if recipient:
                deal.seller_wallet_address = recipient
            token = accepted_token_address(deal.accepted_escrow_proposal)
            if token:
                deal.token_contract = token
        if deal.settlement_plan is not None and not deal.accepted_escrow_terms:
            deal.accepted_escrow_terms = [
                terms.model_dump()
                for terms in escrow_terms_from_settlement_plan(deal.settlement_plan)
            ]

    def listing_rows(self, listing: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        return (("Accepted escrows", format_accepted_escrows(listing.get("accepted_escrows", []))),)

    def open_buy(self, request: BuyRequest) -> AlkahestBuySession:
        return AlkahestBuySession(self, request)

    def resume(self, resume: SettlementResume) -> dict[str, Any]:
        """Create the accepted escrow unless it exists, then submit it to the seller and poll."""
        deal = resume.deal
        options = resume.options
        signer = resume.identity.signer
        chain_cfg_name = (
            options.get("chain_name")
            or _accepted_proposal_chain(deal)
            or _chain_name_from_run_log(resume.run_id, signer=signer)
        )
        if not chain_cfg_name:
            typer.secho(
                "Could not determine the chain from the run-log or deal context. Pass --chain to specify which configured chain to settle on.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        chain_cfg = chain_by_name(chain_cfg_name)
        if deal.accepted_escrow_proposal is None and deal.accepted_escrow_terms is None:
            typer.secho(
                "Run-log carries no seller-accepted escrow proposal. Re-run negotiation so the accepted proposal is captured — token settlement always settles the seller-confirmed shape.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        resolved_evm_address, resolved_evm_private_key = resolve_buyer_wallet(
            override_addr=options.get("evm_address"), override_pk=options.get("evm_private_key")
        )
        if not resolved_evm_address or not resolved_evm_private_key:
            typer.secho(
                "Missing explicit EVM settlement credentials: wallet.address and wallet.private_key are required for Alkahest.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        chain = SimpleNamespace(
            buyer_address=resolved_evm_address,
            buyer_private_key=resolved_evm_private_key,
            rpc_url=chain_cfg.rpc_url,
            chain_name=chain_cfg.name,
            alkahest_addr_config=chain_cfg.alkahest_address_config_path,
        )
        log = resume.open_log()
        resolve_seller_principals = resume.seller_principals(log, resume.buy_config())
        resolved_uid = options.get("escrow_uid") or deal.escrow_uid
        resume.show_header(
            *((("Escrow UID", resolved_uid + " (skip create)"),) if resolved_uid else ())
        )
        console = resume.console
        if not resolved_uid:
            log.event(
                "escrow_create_start",
                terms={
                    "seller_url": deal.seller_url,
                    "listing_id": deal.listing_id,
                    "negotiation_id": deal.negotiation_id,
                    "agreed_amount": deal.agreed_amount,
                    "duration_seconds": 0,
                },
            )
            console.print("[dim]escrow.create[/dim]  approve + create on-chain…")
            if deal.accepted_escrow_terms is not None:
                escrow_terms_list = [
                    EscrowTerms.model_validate(item) for item in deal.accepted_escrow_terms
                ]
            elif deal.accepted_escrow_proposal is None:
                _refuse_without_release_condition(
                    log, "the run-log records no accepted escrow terms or proposal"
                )
            else:
                _refuse_without_release_condition(
                    log, resumed_proposal_refusal(deal.accepted_escrow_proposal)
                )
            create_escrow = make_create_escrow_fn(
                private_key=chain.buyer_private_key,
                rpc_url=chain.rpc_url,
                chain_name=chain.chain_name,
                addr_config_path=chain.alkahest_addr_config,
            )
            try:
                uids = create_escrow(escrow_terms_list)
            except Exception as exc:
                log.event("escrow_create_failed", error=str(exc))
                log.end("error", error=f"escrow_create: {exc}")
                typer.secho(
                    f"escrow.create failed on-chain: {exc}", err=True, fg=typer.colors.RED
                )
                raise typer.Exit(4) from exc
            if not uids:
                log.event("escrow_create_failed", error="no uid returned")
                log.end("error", error="escrow_create: no uid returned")
                typer.secho(
                    "escrow.create returned no uid — buyer terms list was empty.",
                    err=True,
                    fg=typer.colors.RED,
                )
                raise typer.Exit(4)
            resolved_uid = uids[0]
            log.event(
                "escrow_created", escrow_uid=resolved_uid, chain_name=chain.chain_name
            )
            console.print(f"[green]escrow created[/green]  {resolved_uid}")
        try:
            submit_body = submit_settlement_request(
                seller_url=deal.seller_url,
                escrow_uid=resolved_uid,
                payload={
                    "negotiation_id": deal.negotiation_id,
                    "buyer_evm_address": chain.buyer_address,
                    "chain_name": chain.chain_name,
                },
                principal=deal.buyer_principal,
                signer=signer,
                max_attempts=6,
                retryable=looks_like_propagation_lag,
                resolve_seller_principals=resolve_seller_principals,
            )
        except RuntimeError as exc:
            log.event("settle_submit_failed", error=str(exc))
            log.end("error", error=f"settle_submit: {exc}")
            typer.secho(f"/settle submit failed: {exc}", err=True, fg=typer.colors.RED)
            raise typer.Exit(5) from exc
        log.event("settle_submitted", body=submit_body)
        console.print(f"[dim]submitted[/dim]  initial body={submit_body}")

        def _on_poll(attempt: int, body: dict) -> None:
            log.event("settle_status", attempt=attempt, body=body)

        try:
            final = wait_for_settlement(
                seller_url=deal.seller_url,
                escrow_uid=resolved_uid,
                principal=deal.buyer_principal,
                signer=signer,
                poll_interval=resume.poll_interval,
                total_timeout=resume.settlement_timeout,
                on_poll=_on_poll,
                resolve_seller_principals=resolve_seller_principals,
            )
        except TimeoutError as exc:
            log.event("settle_terminal", status="timeout", error=str(exc))
            log.end("timeout", escrow_uid=resolved_uid, error=str(exc))
            typer.secho(
                f"settlement polling timed out: {exc}", err=True, fg=typer.colors.YELLOW
            )
            raise typer.Exit(6) from exc
        log.event("settle_terminal", body=final)
        return resume.finish(
            log,
            final,
            reference=("Escrow UID", resolved_uid),
            end_fields={"escrow_uid": resolved_uid},
            unready_border="yellow",
        )
