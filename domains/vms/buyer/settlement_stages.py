"""VM-owned settlement entries and immutable accepted-work recovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import typer
from arkhai_vms import normalize_vm_provision_terms
from core_buyer import BuyConfig
from core_buyer.orchestration import (
    AgreedTerms as CoreAgreedTerms,
    make_escrow_settle_hook,
    submit_settlement_request,
    wait_for_settlement,
)
from market_alkahest.plans import escrow_terms_from_settlement_plan
from market_alkahest.schemas import (
    EscrowProposal,
    EscrowTerms,
    accepted_recipient_address,
    accepted_token_address,
)
from market_arkhai_payments import Mandate
from market_alkahest.token import TokenResolutionError, resolve_token
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import common
from .arkhai_payments import (
    AgreedTerms,
    make_payment_settle_hook,
    payer_selection,
    payment_buyer,
    settle_payment,
)
from .deal_helpers import ChainSettings, resolve_chain_settings
from .escrow_client import (
    accepted_proposal_recipient,
    looks_like_propagation_lag,
    make_alkahest_settlement_payload_fn,
    make_buyer_payment_escrow_terms_fn,
    make_create_escrow_fn,
)
from .run_log import read_run


@dataclass(frozen=True)
class BuyerStageContext:
    config: BuyConfig
    provision: Any
    resolve_policy: Callable[[], Any]
    poll_interval: float
    timeout: float
    sleep: Callable[[float], None]
    confirm: Callable | None = None
    buyer_evm_address: str = ""
    build_escrow_terms: Callable | None = None
    create_escrow: Callable | None = None


@dataclass(frozen=True)
class BuyerResumeContext:
    run_id: str
    deal: Any
    log: Any
    signer: Any
    resolve_seller_principals: Callable
    resolve_policy: Callable[[], Any]
    resolve_address_config: Callable[[], str | None]
    poll_interval: float
    timeout: float
    console: Console


@dataclass(frozen=True)
class AlkahestBuyerStage:
    """Bind accepted escrow artifacts and EVM effects to the Alkahest helper."""

    def validate_acceptance(self, outcome):
        if outcome.accepted_escrow_proposal is None:
            raise RuntimeError("seller omitted accepted_escrow_proposal for Alkahest")
        if outcome.settlement_selection is not None and outcome.settlement_plan is None:
            raise RuntimeError("seller omitted settlement_plan for Alkahest")

    def readiness_resources(self):
        chains = common.buyer_chains()
        address, _private_key = common.resolve_buyer_wallet()
        resources = {"chains": chains, "wallet": {"address": address}}
        if len(chains) == 1:
            resources["default_chain"] = next(iter(chains))
        return resources

    def prepare_selection(self, selected):
        return selected

    def accepted_entry(self, selected):
        value = selected.option.params.get("accepted_escrow")
        if not isinstance(value, Mapping):
            raise ValueError("selected Alkahest option has no accepted escrow payload")
        return dict(value)

    def negotiation_prices(
        self, selected, *, policy, initial_price, max_price,
        initial_explicit, max_explicit,
    ):
        entry = self.accepted_entry(selected)
        if not policy.compatible(entry):
            raise ValueError("selected Alkahest option is incompatible with buyer policy")
        name = entry.get("chain_name")
        if not isinstance(name, str) or not name:
            raise ValueError("selected Alkahest option has no chain identity")
        chain = common.chain_by_name(name)
        address, private_key = common.resolve_buyer_wallet()
        if not address or not private_key:
            raise ValueError("selected Alkahest settlement requires [Wallet] credentials")
        if initial_explicit or max_explicit:
            try:
                decimals = resolve_token(
                    accepted_token_address(entry), rpc_url=chain.rpc_url,
                    chain_id=chain.chain_id,
                ).decimals
            except (TokenResolutionError, RuntimeError) as exc:
                raise ValueError("could not resolve selected Alkahest token decimals") from exc
            scale = 10**decimals
            if initial_explicit and initial_price is not None:
                initial_price *= scale
            if max_explicit and max_price is not None:
                max_price *= scale
        return initial_price, max_price

    def proposal(self, match, selected):
        return selected.selection

    def enrich_deal(self, deal):
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

    def settle(self, context, negotiation, on_event):
        self.validate_acceptance(negotiation.outcome)
        build_terms = context.build_escrow_terms
        create = context.create_escrow
        address = context.buyer_evm_address
        if build_terms is None or create is None:
            proposal = negotiation.outcome.accepted_escrow_proposal
            chain = common.chain_by_name(proposal.chain_name)
            address, private_key = common.resolve_buyer_wallet()
            if not address or not private_key:
                raise ValueError("selected Alkahest settlement requires [Wallet] credentials")
            policy = context.resolve_policy()
            section = policy.config.mechanism_config("alkahest")
            path = getattr(section, "address_config_path", None)
            build_terms = build_terms or make_buyer_payment_escrow_terms_fn(
                chain_name=chain.name, addr_config_path=path,
            )
            create = create or make_create_escrow_fn(
                private_key=private_key, rpc_url=chain.rpc_url,
                chain_name=chain.name, addr_config_path=path,
            )
        confirm = None
        if context.confirm is not None:
            def confirm(terms: CoreAgreedTerms, match):
                return context.confirm(AgreedTerms(
                    terms.seller_url, terms.seller_wallet_address,
                    terms.negotiation_id, terms.listing_id, terms.agreed_amount,
                    context.provision.duration_seconds,
                ), match)
        hook = make_escrow_settle_hook(
            config=context.config,
            unit_count=float(context.provision.duration_seconds) / 3600.0,
            duration_seconds=context.provision.duration_seconds,
            build_escrow_terms=build_terms, create_escrow=create,
            settlement_recipient=accepted_proposal_recipient,
            build_settlement_payload=make_alkahest_settlement_payload_fn(
                buyer_evm_address=address,
                ssh_public_key=context.provision.ssh_public_key,
            ),
            settlement_submit_max_attempts=6,
            settlement_submit_retryable=looks_like_propagation_lag,
            confirm_settlement=confirm,
            settlement_poll_interval=context.poll_interval,
            settlement_total_timeout=context.timeout, sleep=context.sleep,
        )
        return hook(negotiation, on_event)

    def resume(self, context):
        return _resume_alkahest(context)


@dataclass(frozen=True)
class PaymentsBuyerStage:
    """Bind mandate validation and owner-scoped payment approval."""

    def validate_acceptance(self, outcome):
        data = outcome.settlement_data or {}
        if not isinstance(data.get("mandate"), Mapping):
            raise RuntimeError("seller did not supply a payment mandate")
        Mandate.model_validate(data["mandate"])

    def readiness_resources(self):
        return {}

    def prepare_selection(self, selected):
        return payer_selection(selected)

    def accepted_entry(self, selected):
        return None

    def negotiation_prices(self, selected, *, initial_price, max_price, **_):
        return initial_price, max_price

    def proposal(self, match, selected):
        return selected.selection

    def enrich_deal(self, deal):
        pass

    def settle(self, context, negotiation, on_event):
        self.validate_acceptance(negotiation.outcome)
        return make_payment_settle_hook(
            config=context.config, policy=context.resolve_policy(),
            timeout=context.timeout, interval=context.poll_interval,
            confirm_settlement=context.confirm,
        )(negotiation, on_event)

    def resume(self, context):
        deal, log = context.deal, context.log
        if deal.agreement_bytes is None or deal.settlement_data is None:
            raise ValueError("run has no accepted Agreement and payment mandate")
        final = settle_payment(
            buyer=payment_buyer(context.resolve_policy()),
            agreement_bytes=deal.agreement_bytes, settlement_data=deal.settlement_data,
            seller_url=deal.seller_url, principal=deal.buyer_principal,
            signer=context.signer,
            resolve_seller_principals=context.resolve_seller_principals,
            negotiation_id=deal.negotiation_id, timeout=context.timeout,
            interval=context.poll_interval,
            on_event=lambda stage, body: log.event(stage, **body),
        )
        log.end(final.get("status") or "unknown", escrow_uid=deal.negotiation_id)
        context.console.print(Panel(str(final), title="Settlement complete"))
        if final.get("status") != "ready":
            raise typer.Exit(7)
        return final


def _chain_name_from_run_log(run_id: str, *, signer) -> str | None:
    """Look up the explicit EVM mechanism chain recorded for a run."""
    for ev in read_run(run_id, signer=signer):
        if ev.get("event") == "escrow_created":
            chain_name = ev.get("chain_name")
            if isinstance(chain_name, str) and chain_name:
                return chain_name
            terms = ev.get("terms") or {}
            chain_name = terms.get("chain_name")
            if isinstance(chain_name, str) and chain_name:
                return chain_name
        if ev.get("event") == "run_started":
            chain_name = ev.get("chain_name")
            if isinstance(chain_name, str) and chain_name:
                return chain_name
    return None


def _first_listing_chain(deal) -> str | None:
    """Fallback: pick the chain from the deal's listing accepted_escrows."""
    listing = getattr(deal, "listing", None)
    if isinstance(listing, dict):
        for entry in listing.get("accepted_escrows") or []:
            if isinstance(entry, dict):
                cn = entry.get("chain_name")
                if isinstance(cn, str) and cn:
                    return cn
    return None


def _accepted_proposal_chain(deal) -> str | None:
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


def _accepted_provision_inputs(deal) -> tuple[str | None, int]:
    """Recover immutable provision inputs, reserving config for legacy absence."""
    raw = deal.accepted_provision_terms
    if raw is None:
        if deal.settlement_selection is not None or deal.settlement_plan is not None:
            raise typer.BadParameter(
                "accepted settlement state omitted accepted_provision_terms; current configuration will not reinterpret this run"
            )
        return (None, int(deal.duration_seconds))
    try:
        accepted = normalize_vm_provision_terms(raw)
    except (TypeError, ValueError) as exc:
        raise typer.BadParameter(
            "run-log has malformed accepted VM provision terms"
        ) from exc
    ssh_public_key = accepted.ssh_public_key.strip()
    if not ssh_public_key:
        raise typer.BadParameter(
            "accepted VM provision terms have no SSH public key; current configuration will not reinterpret this run"
        )
    return (ssh_public_key, accepted.duration_seconds)


def _resume_alkahest(context: BuyerResumeContext) -> dict:
    run_id, deal, log, signer = context.run_id, context.deal, context.log, context.signer
    resolve_seller_principals = context.resolve_seller_principals
    poll_interval, settlement_timeout = context.poll_interval, context.timeout
    console = context.console
    if (
        not deal.escrow_uid
        and deal.accepted_escrow_proposal is None
        and deal.accepted_escrow_terms is None
    ):
        raise typer.BadParameter("accepted Alkahest work has no escrow artifacts; recovery will not synthesize them")
    alkahest_address_config_path = context.resolve_address_config()
    accepted_ssh_public_key, effective_duration = _accepted_provision_inputs(deal)
    effective_token = deal.token_contract
    effective_token_decimals: int | None = (
        int(deal.token_decimals) if deal.token_decimals is not None else None
    )
    chain_cfg_name = (
        _accepted_proposal_chain(deal)
        or _chain_name_from_run_log(run_id, signer=signer)
        or _first_listing_chain(deal)
    )
    if not chain_cfg_name:
        typer.secho(
            "Could not derive the selected EVM chain from accepted state.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    chain_cfg = common.chain_by_name(chain_cfg_name)
    chain: SimpleNamespace | ChainSettings
    if deal.accepted_escrow_proposal is not None:
        resolved_buyer_address, resolved_buyer_private_key = common.resolve_buyer_wallet()
        resolved_ssh_public_key = (
            accepted_ssh_public_key
            if accepted_ssh_public_key is not None
            else common.resolve_ssh_public_key()
        )
        missing: list[str] = []
        if not resolved_buyer_address:
            missing.append("wallet.address")
        if not resolved_buyer_private_key:
            missing.append("wallet.private_key")
        if not resolved_ssh_public_key:
            missing.append("provisioning.ssh_public_key")
        if missing:
            typer.secho(
                "Missing required EVM config: " + ", ".join(missing),
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(2)
        chain = SimpleNamespace(
            buyer_address=resolved_buyer_address,
            buyer_private_key=resolved_buyer_private_key,
            ssh_public_key=resolved_ssh_public_key,
            rpc_url=chain_cfg.rpc_url,
            chain_name=chain_cfg.name,
            alkahest_addr_config=alkahest_address_config_path,
            token_contract=effective_token or "",
            token_decimals=effective_token_decimals,
        )
    else:
        chain = resolve_chain_settings(
            buyer_address=None,
            buyer_private_key=None,
            ssh_public_key=accepted_ssh_public_key,
            chain=chain_cfg,
            token_contract=effective_token,
            token_decimals=effective_token_decimals,
        )
        chain.alkahest_addr_config = alkahest_address_config_path
    resolved_uid = deal.escrow_uid
    header = Table.grid(padding=(0, 2))
    header.add_column(style="bold")
    header.add_column()
    header.add_row("Run ID", run_id)
    header.add_row("Seller", deal.seller_url)
    header.add_row("Negotiation", deal.negotiation_id)
    header.add_row("Agreed price (per hour)", str(deal.agreed_amount))
    header.add_row("Duration (seconds)", str(effective_duration))
    if chain.token_contract:
        header.add_row(
            "Token", f"{chain.token_contract} (decimals={chain.token_decimals})"
        )
    if resolved_uid:
        header.add_row("Escrow UID", resolved_uid + " (skip create)")
    console.print(Panel(header, title="market settle", border_style="cyan"))
    if not resolved_uid:
        seller_wallet = deal.seller_wallet_address
        if not seller_wallet and deal.accepted_escrow_proposal is None:
            error = "Run-log does not contain a seller recipient. Re-run negotiation so the accepted escrow proposal is captured."
            log.event("escrow_recipient_missing", error=error)
            log.end("error", error=error)
            typer.secho(error, err=True, fg=typer.colors.RED)
            raise typer.Exit(3)
        terms = AgreedTerms(
            seller_url=deal.seller_url,
            seller_wallet_address=seller_wallet or "",
            negotiation_id=deal.negotiation_id,
            listing_id=deal.listing_id,
            agreed_amount=deal.agreed_amount,
            duration_seconds=effective_duration,
        )
        log.event("escrow_create_start", terms=terms.__dict__)
        console.print("[dim]escrow.create[/dim]  approve + create on-chain…")
        if deal.accepted_escrow_terms is not None:
            escrow_terms_list = [
                EscrowTerms.model_validate(item) for item in deal.accepted_escrow_terms
            ]
        else:
            proposal = EscrowProposal(**deal.accepted_escrow_proposal)
        if deal.accepted_escrow_terms is None:
            build_terms = make_buyer_payment_escrow_terms_fn(
                chain_name=chain.chain_name, addr_config_path=chain.alkahest_addr_config
            )
            escrow_terms_list = build_terms(
                proposal,
                seller_wallet,
                int(deal.agreed_amount),
                int(effective_duration),
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
        log.event("escrow_created", escrow_uid=resolved_uid)
        console.print(f"[green]escrow created[/green]  {resolved_uid}")
    try:
        submit_body = submit_settlement_request(
            seller_url=deal.seller_url,
            escrow_uid=resolved_uid,
            payload={
                "negotiation_id": deal.negotiation_id,
                "ssh_public_key": chain.ssh_public_key,
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
            resolve_seller_principals=resolve_seller_principals,
            poll_interval=poll_interval,
            total_timeout=settlement_timeout,
            on_poll=_on_poll,
        )
    except TimeoutError as exc:
        log.event("settle_terminal", status="timeout", error=str(exc))
        log.end("timeout", escrow_uid=resolved_uid, error=str(exc))
        typer.secho(
            f"settlement polling timed out: {exc}", err=True, fg=typer.colors.YELLOW
        )
        raise typer.Exit(6) from exc
    log.event("settle_terminal", body=final)
    log.end(
        final.get("status") or "unknown",
        escrow_uid=resolved_uid,
        fulfillment_uid=final.get("fulfillment_uid"),
    )
    result = Table.grid(padding=(0, 2))
    result.add_column(style="bold")
    result.add_column()
    result.add_row("Status", str(final.get("status")))
    result.add_row("Escrow UID", resolved_uid)
    if final.get("fulfillment_uid"):
        result.add_row("Fulfillment UID", str(final["fulfillment_uid"]))
    if final.get("connection_details"):
        result.add_row("Connection", str(final["connection_details"]))
    if final.get("reason"):
        result.add_row("Reason", str(final["reason"]))
    border = "green" if final.get("status") == "ready" else "yellow"
    console.print(Panel(result, title="Settlement complete", border_style=border))
    if final.get("status") != "ready":
        raise typer.Exit(7)
    return final
