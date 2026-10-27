"""The buyer's Alkahest stage: escrow selection, negotiation pricing, escrow creation, and resumption."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Optional

import typer
from arkhai_api_buying.credentials import error_text, public_fields
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
    EscrowProposal,
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
    accepted_chain_names,
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


def _proposal_chain(proposal: Any) -> Optional[str]:
    chain = proposal.get("chain_name") if isinstance(proposal, Mapping) else getattr(proposal, "chain_name", None)
    return chain if isinstance(chain, str) and chain else None


def token_decimals(chain: Any, token: Optional[str]) -> int:
    """The ERC-20 ``token``'s decimals read on ``chain``; refuses a native-token escrow or an unreadable token."""
    if not token:
        typer.secho(
            f"Explicit prices need an ERC-20 token to scale, but a selected escrow on chain "
            f"{chain.name!r} settles in the native token; omit --initial-price/--max-price.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    try:
        return resolve_token(token, rpc_url=chain.rpc_url, chain_id=chain.chain_id).decimals
    except (TokenResolutionError, RuntimeError) as exc:
        typer.secho(
            f"Could not read the decimals of token {token} on chain {chain.name!r}; check "
            f"the chain's rpc_url. ({exc})",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2) from exc


class AlkahestBuySession:
    """The Alkahest part of one buy: the configured wallet and chains, a chain per listing, and its escrow adapters."""

    def __init__(self, stage: AlkahestBuyerStage, request: BuyRequest) -> None:
        self._stage = stage
        self._request = request
        self._address: str | None = None
        self._private_key: str | None = None
        self._chains: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        return bool(self._address and self._private_key and self._chains)

    def prepare(self) -> None:
        if not self._request.enabled:
            return
        self._address, self._private_key = self._stage.wallet()
        self._chains = self._stage.chains()

    def missing(self) -> tuple[tuple[str, str], ...]:
        missing = []
        if not self._address:
            missing.append(("buyer_evm_address", "wallet.address"))
        if not self._private_key:
            missing.append(("buyer_evm_private_key", "wallet.private_key"))
        if not self._stage.chains():
            missing.append(("chain configuration", "chains.<name>"))
        return tuple(missing)

    def scale_explicit_prices(
        self, initial: Any, maximum: Any, matches: Iterable[Mapping[str, Any]],
    ) -> tuple[Any, Any]:
        tokens = {
            (proposal.chain_name, accepted_token_address(proposal))
            for proposal in (match.get("_selected_buyer_proposal") for match in matches)
            if isinstance(proposal, EscrowProposal)
        }
        if not self.available or not tokens:
            return initial, maximum
        decimals = {token_decimals(self._chains[chain_name], token) for chain_name, token in tokens}
        if len(decimals) != 1:
            typer.secho(
                "--initial-price and --max-price are in display units, but the selected "
                f"listings settle in tokens of different decimals ({sorted(tokens)}); "
                "buy from one token's listings at a time.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        (scale,) = decimals
        try:
            return (
                display_to_base_units(initial, scale, field="--initial-price"),
                display_to_base_units(maximum, scale, field="--max-price"),
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    def propose(self, listing: Mapping[str, Any], *, expiration_unix: int) -> Any | None:
        if not self.available or not accepted_chain_names(dict(listing)) & set(self._chains):
            return None
        chain = select_chain_for_listing(
            dict(listing), yes=self._request.assume_yes, chains=self._chains,
        )
        policy = self._request.policy
        entry = select_escrow_entry(
            listing,
            chain_name=chain.name,
            token_contract_filter=None,
            assume_yes=self._request.assume_yes,
            rpc_url=chain.rpc_url,
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
        return {"buyer_evm_address": self._address}

    def header_rows(self) -> tuple[tuple[str, str], ...]:
        return (("EVM chain wallet", self._address),) if self._address else ()

    def settle(self, negotiation: Any, on_event: Any, run: BuyRun) -> Any:
        self._stage.validate_acceptance(negotiation.outcome)
        if not self.available:
            raise ValueError("Alkahest settlement resources are unavailable")
        chain = self._chains.get(_proposal_chain(negotiation.outcome.accepted_escrow_proposal) or "")
        if chain is None:
            raise ValueError("the accepted Alkahest escrow names no configured chain")
        address_config = chain.alkahest_address_config_path or None
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
            build_escrow_terms=make_buyer_payment_escrow_terms_fn(
                chain_name=chain.name, addr_config_path=address_config
            ),
            create_escrow=make_create_escrow_fn(
                private_key=self._private_key,
                rpc_url=chain.rpc_url,
                chain_name=chain.name,
                addr_config_path=address_config,
            ),
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
    options: tuple[StageOption, ...] = ()
    registration = staticmethod(create_alkahest_registration)

    def __init__(
        self,
        *,
        wallet: Callable[[], tuple[str | None, str | None]] | None = None,
        chains: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._wallet = wallet
        self._chains = chains

    def wallet(self) -> tuple[str | None, str | None]:
        return (self._wallet or resolve_buyer_wallet)()

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
            "chain_name": self.accepted_entry(selected).get("chain_name") if selected else None,
        }

    def prepare_selection(
        self, selected: Any, *, listing: Any, settlement_policy: Any, policy: Any,
        options: StageOptions, assume_yes: bool, console: Any,
    ) -> Any:
        address, _key = self.wallet()
        if not address:
            raise ValueError(
                "Missing EVM address required to select and inspect the Alkahest "
                "escrow. Configure wallet.address or wallet.private_key."
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
        chain = select_chain_for_listing(constrained, yes=assume_yes, chains=self.chains())
        entry = select_escrow_entry(
            constrained, chain_name=chain.name, token_contract_filter=None,
            assume_yes=assume_yes, rpc_url=chain.rpc_url, buyer_address=address,
            console=console, compatible=policy.compatible,
            preference=policy.prefer_settlement,
        )
        if entry is None:
            raise ValueError(
                f"Listing {listing.get('listing_id')!r} has no accepted_escrows entry "
                f"on chain {chain.name!r}."
            )
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
        if not (initial_explicit or max_explicit):
            return initial_price, max_price
        entry = self.accepted_entry(selected)
        chain = self.chains().get(entry.get("chain_name") or "")
        if chain is None:
            raise ValueError(
                f"The selected escrow's chain {entry.get('chain_name')!r} is not in [chains.<name>]."
            )
        decimals = token_decimals(chain, accepted_token_address(entry))
        if initial_explicit and initial_price is not None:
            initial_price = display_to_base_units(initial_price, decimals, field="--initial-price")
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
        signer = resume.identity.signer
        chain_cfg_name = (
            _accepted_proposal_chain(deal)
            or _chain_name_from_run_log(resume.run_id, signer=signer)
        )
        if not chain_cfg_name:
            typer.secho(
                "Could not determine the chain from the run-log's accepted escrow. Re-run negotiation so the accepted proposal is captured.",
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
        resolved_evm_address, resolved_evm_private_key = self.wallet()
        if not resolved_evm_address or not resolved_evm_private_key:
            typer.secho(
                "Missing EVM settlement credentials: configure wallet.private_key (and wallet.address, if it differs) for Alkahest.",
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
        resolved_uid = deal.escrow_uid
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
                reason = error_text(exc, log.secrets)
                log.event("escrow_create_failed", error=reason)
                log.end("error", error=f"escrow_create: {reason}")
                typer.secho(
                    f"escrow.create failed on-chain: {reason}", err=True, fg=typer.colors.RED
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
            reason = error_text(exc, log.secrets)
            log.event("settle_submit_failed", error=reason)
            log.end("error", error=f"settle_submit: {reason}")
            typer.secho(f"/settle submit failed: {reason}", err=True, fg=typer.colors.RED)
            raise typer.Exit(5) from exc
        log.event("settle_submitted", body=submit_body)
        console.print(f"[dim]submitted[/dim]  initial body={public_fields(submit_body, log.secrets)}")

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
            reason = error_text(exc, log.secrets)
            log.event("settle_terminal", status="timeout", error=reason)
            log.end("timeout", escrow_uid=resolved_uid, error=reason)
            typer.secho(
                f"settlement polling timed out: {reason}", err=True, fg=typer.colors.YELLOW
            )
            raise typer.Exit(6) from exc
        except RuntimeError as exc:
            reason = error_text(exc, log.secrets)
            log.event("settle_status_failed", error=reason)
            log.end("error", escrow_uid=resolved_uid, error=f"settle_status: {reason}")
            typer.secho(f"/settle status failed: {reason}", err=True, fg=typer.colors.RED)
            raise typer.Exit(5) from exc
        log.event("settle_terminal", body=final)
        return resume.finish(
            log,
            final,
            reference=("Escrow UID", resolved_uid),
            end_fields={"escrow_uid": resolved_uid},
            unready_border="yellow",
        )
