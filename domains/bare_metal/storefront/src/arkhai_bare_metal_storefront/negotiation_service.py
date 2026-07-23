"""Bare-metal-owned orchestration for the shared negotiation wire contract."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_bare_metal import BareMetalMessage, BareMetalTerms
from core_storefront.models.negotiation_models import (
    NegotiateNewRequest,
    NegotiateNewResponse,
)
from market_core import MarketDomainContract
from market_core.schemas import (
    AcceptedEscrow,
    EscrowProposal,
    SettlementPlan,
    compute_rate_total,
)
from market_policy.negotiation_middleware import NegotiationRound

from .negotiation import BareMetalSellerRoundHook
from .sqlite_client import SQLiteClient


class NegotiationRequestError(ValueError):
    """A request cannot enter bare-metal negotiation."""

    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


PlanBuilder = Callable[..., dict[str, Any]]


def _matching_acceptance(
    listing: Mapping[str, Any],
    proposal: EscrowProposal,
) -> AcceptedEscrow | None:
    for raw in listing.get("accepted_escrows") or []:
        accepted = AcceptedEscrow.model_validate(raw)
        if (
            accepted.chain_name == proposal.chain_name
            and accepted.escrow_address.lower() == proposal.escrow_address.lower()
        ):
            return accepted
    return None


def _proposal_amount(proposal: EscrowProposal) -> int | None:
    raw = proposal.fields.get("amount")
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int) and raw >= 0:
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip())
    raise NegotiationRequestError("proposal amount must be a non-negative integer", status_code=400)


def _seller_reference_amount(
    accepted: AcceptedEscrow | None,
    *,
    duration_seconds: int,
    buyer_amount: int | None,
) -> int:
    if accepted is None:
        return 0
    amount_rates = [rate for rate in accepted.rates if rate.field == "amount"]
    if amount_rates:
        return compute_rate_total(amount_rates[0], duration_seconds)
    if buyer_amount is not None:
        raise NegotiationRequestError(
            "scalar listing has no advertised amount rate",
            status_code=409,
        )
    return 0


@dataclass(frozen=True)
class BareMetalNegotiationService:
    db: SQLiteClient
    domain: MarketDomainContract
    seller_id: str
    round_hook: BareMetalSellerRoundHook
    build_plan: PlanBuilder

    async def open(
        self,
        *,
        request: NegotiateNewRequest,
        buyer_identity: str,
    ) -> NegotiateNewResponse:
        if await self.db.is_global_paused():
            raise NegotiationRequestError("storefront paused", status_code=503)
        listing = await self.db.load_listing(listing_id=request.listing_id)
        if listing is None:
            raise NegotiationRequestError("listing not found", status_code=404)
        if listing.get("status") != "open":
            raise NegotiationRequestError("listing is not open")
        if bool(listing.get("paused")):
            raise NegotiationRequestError("listing paused", status_code=503)

        try:
            message = self.domain.codecs.message(request.provision_terms)
        except Exception as exc:
            raise NegotiationRequestError(
                "incompatible bare-metal provision terms",
                status_code=400,
            ) from exc
        assert isinstance(message, BareMetalMessage)
        proposal = EscrowProposal.model_validate(request.proposal)
        buyer_amount = _proposal_amount(proposal)
        accepted = _matching_acceptance(listing, proposal)
        if not (listing.get("accepted_escrows") or []):
            raise NegotiationRequestError(
                "listing has no accepted escrow contract",
                status_code=409,
            )
        reference_amount = _seller_reference_amount(
            accepted,
            duration_seconds=message.duration_seconds,
            buyer_amount=buyer_amount,
        )
        proposal_payload = proposal.model_dump(mode="json", exclude_none=True)
        result = await self.round_hook(
            listing=listing,
            message=message,
            history=[
                NegotiationRound(
                    round_number=0,
                    sender="them",
                    action="initial",
                    proposal=proposal_payload,
                ),
            ],
            seller_reference_amount=reference_amount,
            listing_ref=request.listing_id,
        )
        decision = result.decision
        if decision.action in {"reject", "exit"}:
            raise NegotiationRequestError(
                decision.reason or "offer unfulfillable",
                status_code=409,
            )

        intermediate = dict(result.intermediate or {})
        terms_raw = intermediate.get("bare_metal_terms")
        terms = (
            self.domain.codecs.terms(terms_raw)
            if decision.action == "accept" and terms_raw is not None
            else None
        )
        assert terms is None or isinstance(terms, BareMetalTerms)
        decision_payload = decision.proposal or proposal_payload
        seller_amount = _proposal_amount(
            EscrowProposal.model_validate(decision_payload),
        )
        agreed_amount = (
            (buyer_amount if buyer_amount is not None else 0)
            if decision.action == "accept"
            else None
        )
        artifacts: dict[str, Any] = {}
        if terms is not None:
            artifacts = self.build_plan(
                proposal=proposal,
                agreed_amount=agreed_amount or 0,
                duration_seconds=terms.duration_seconds,
                uses_scalar_amount=bool(intermediate.get("uses_scalar_amount", True)),
            )

        negotiation_id = f"neg_{uuid.uuid4().hex}"
        await self.db.persist_bare_metal_opening(
            negotiation_id=negotiation_id,
            listing_id=request.listing_id,
            seller_id=self.seller_id,
            buyer_agent_id=request.buyer_agent_url or buyer_identity,
            buyer_identity=buyer_identity,
            seller_reference_amount=reference_amount,
            strategy=result.strategy_label,
            message=message,
            proposal=proposal_payload,
            buyer_amount=buyer_amount,
            seller_action=decision.action,
            seller_amount=seller_amount,
            terms=terms,
            agreed_amount=agreed_amount,
        )
        settlement_plan = artifacts.get("settlement_plan")
        legacy_terms = artifacts.get("accepted_escrow_terms")
        return NegotiateNewResponse(
            negotiation_id=negotiation_id,
            action=decision.action,
            proposal=decision_payload,
            reason=decision.reason,
            accepted_provision_terms=(
                request.provision_terms if decision.action == "accept" else None
            ),
            accepted_escrow_proposal=(
                proposal if decision.action == "accept" else None
            ),
            settlement_plan=(
                SettlementPlan.model_validate(settlement_plan)
                if settlement_plan is not None
                else None
            ),
            accepted_escrow_terms=legacy_terms,
        )
