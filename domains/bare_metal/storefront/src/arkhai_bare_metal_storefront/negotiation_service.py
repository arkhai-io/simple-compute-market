"""Bare-metal-owned orchestration for the shared negotiation wire contract."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_bare_metal import (
    HOSTED_MECHANISM,
    BareMetalBuyerDemand,
    BareMetalMessage,
    BareMetalTerms,
    validate_buyer_selection,
)
from core_storefront.models.negotiation_models import (
    NegotiateNewRequest,
    NegotiateNewResponse,
)
from market_core import MarketDomainContract
from market_core.schemas import (
    AcceptedEscrow,
    EscrowProposal,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    compute_rate_total,
)
from market_policy.negotiation_middleware import NegotiationRound
from market_identity import Identity

from .hosted_binding import build_accepted_hosted_plan

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
    raise NegotiationRequestError(
        "proposal amount must be a non-negative integer", status_code=400
    )


def _exact_selection(request: NegotiateNewRequest) -> SettlementSelection | None:
    direct = request.settlement_selection
    nested: SettlementSelection | None = None
    proposal = request.proposal
    if (
        isinstance(proposal, Mapping)
        and proposal.get("settlement_selection") is not None
    ):
        unknown = sorted(set(proposal).difference({"settlement_selection", "fields"}))
        fields = proposal.get("fields", {})
        if unknown or not isinstance(fields, Mapping):
            raise NegotiationRequestError(
                "hosted settlement proposal has invalid fields",
                status_code=400,
            )
        try:
            nested = SettlementSelection.model_validate(
                proposal.get("settlement_selection")
            )
        except (TypeError, ValueError) as exc:
            raise NegotiationRequestError(
                "hosted settlement proposal has an invalid selection",
                status_code=400,
            ) from exc
    if direct is not None and isinstance(proposal, Mapping) and nested is None:
        unknown = sorted(set(proposal).difference({"fields"}))
        if unknown:
            raise NegotiationRequestError(
                "hosted settlement proposal mixes incompatible carriers",
                status_code=400,
            )
    if direct is not None and nested is not None and direct != nested:
        raise NegotiationRequestError(
            "hosted settlement proposal contains ambiguous selections",
            status_code=400,
        )
    selected = direct or nested
    if selected is not None and selected.mechanism != HOSTED_MECHANISM:
        raise NegotiationRequestError(
            "exact settlement selection uses an unsupported mechanism",
            status_code=400,
        )
    return selected


def _hosted_proposal_amount(request: NegotiateNewRequest) -> int | None:
    proposal = request.proposal
    if not isinstance(proposal, Mapping):
        return None
    fields = proposal.get("fields", {})
    if not isinstance(fields, Mapping):
        raise NegotiationRequestError(
            "hosted settlement proposal fields must be an object",
            status_code=400,
        )
    unknown = sorted(set(fields).difference({"amount"}))
    if unknown:
        raise NegotiationRequestError(
            "hosted settlement proposal may contain only amount",
            status_code=400,
        )
    value = fields.get("amount")
    if value is None:
        return None
    if isinstance(value, bool):
        raise NegotiationRequestError(
            "hosted settlement amount must be a non-negative integer",
            status_code=400,
        )
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise NegotiationRequestError(
        "hosted settlement amount must be a non-negative integer",
        status_code=400,
    )


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
    seller_principal: Identity
    round_hook: BareMetalSellerRoundHook
    build_plan: PlanBuilder

    async def open(
        self,
        *,
        request: NegotiateNewRequest,
        buyer_principal: Identity,
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
        selection = _exact_selection(request)
        if selection is not None:
            return await self._open_hosted(
                request=request,
                buyer_principal=buyer_principal,
                listing=listing,
                message=message,
                selection=selection,
            )
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
                buyer_principal=buyer_principal,
                seller_principal=self.seller_principal,
            )

        negotiation_id = f"neg_{uuid.uuid4().hex}"
        await self.db.persist_bare_metal_opening(
            negotiation_id=negotiation_id,
            listing_id=request.listing_id,
            seller_principal=self.seller_principal,
            buyer_agent_id=request.buyer_agent_url,
            buyer_principal=buyer_principal,
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
            buyer_principal=buyer_principal,
            seller_principal=self.seller_principal,
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

    async def _open_hosted(
        self,
        *,
        request: NegotiateNewRequest,
        buyer_principal: Identity,
        listing: Mapping[str, Any],
        message: BareMetalMessage,
        selection: SettlementSelection,
    ) -> NegotiateNewResponse:
        """Accept one exact hosted option without entering escrow negotiation."""

        if (
            Identity.model_validate(listing.get("seller_principal"))
            != self.seller_principal
        ):
            raise NegotiationRequestError("listing seller identity changed")
        try:
            options = [
                SettlementOption.model_validate(value)
                for value in listing.get("settlement_options") or []
            ]
            demand = BareMetalBuyerDemand(
                duration_seconds=message.duration_seconds,
                access_method=message.access_method,
                ssh_public_key=message.ssh_public_key or "",
                settlement=selection,
                allow_off_session=next(
                    (
                        option.params.get("interaction") == "off_session"
                        for option in options
                        if option.option_id == selection.option_id
                    ),
                    False,
                ),
            )
            selected = validate_buyer_selection(
                demand=demand,
                advertised_options=options,
            )
        except (TypeError, ValueError) as exc:
            raise NegotiationRequestError(
                "hosted selection does not exact-match one trusted listing option",
                status_code=400,
            ) from exc
        trusted_listing = await self.db.load_bare_metal_listing_payload(
            listing_id=request.listing_id
        )
        listing_binding = await self.db.load_listing_binding(
            listing_id=request.listing_id
        )
        if trusted_listing is None or listing_binding is None:
            raise NegotiationRequestError("trusted bare-metal listing is unavailable")
        facts = selected.facts
        if (
            facts.site_id != listing_binding.site_id
            or facts.physical_resource_id != listing_binding.physical_resource_id
            or facts.pool_id != listing_binding.pool_id
            or facts.physical_host_id != trusted_listing.physical_host_id
            or facts.access_method != message.access_method
        ):
            raise NegotiationRequestError(
                "hosted selection changes trusted physical listing terms"
            )
        if (
            trusted_listing.min_duration_seconds is not None
            and message.duration_seconds < trusted_listing.min_duration_seconds
        ) or (
            trusted_listing.max_duration_seconds is not None
            and message.duration_seconds > trusted_listing.max_duration_seconds
        ):
            raise NegotiationRequestError(
                "hosted selection duration is outside listing bounds"
            )
        if message.access_method not in trusted_listing.access_methods:
            raise NegotiationRequestError(
                "hosted selection uses an unadvertised access method"
            )
        if message.access_ref is not None:
            raise NegotiationRequestError(
                "buyer cannot supply hosted bare-metal access authority",
                status_code=400,
            )
        terms = BareMetalTerms(
            machine_id=trusted_listing.machine_id,
            physical_host_id=trusted_listing.physical_host_id,
            duration_seconds=message.duration_seconds,
            access_method=message.access_method,
            ssh_public_key=message.ssh_public_key,
            listing_ref=request.listing_id,
        )
        trusted_amount = compute_rate_total(
            selected.option.rates[0],
            message.duration_seconds,
        )
        proposed_amount = _hosted_proposal_amount(request)
        if proposed_amount is not None and proposed_amount != trusted_amount:
            raise NegotiationRequestError(
                "hosted settlement amount differs from trusted duration-scaled rate",
                status_code=400,
            )
        try:
            plan = build_accepted_hosted_plan(
                listing_id=request.listing_id,
                option=selected,
                demand=demand,
                seller_terms=terms,
                buyer_principal=buyer_principal,
                seller_principal=self.seller_principal,
            )
        except (TypeError, ValueError) as exc:
            raise NegotiationRequestError(
                "hosted listing option cannot produce an exact accepted plan"
            ) from exc
        proposal_payload = {
            "settlement_selection": selection.model_dump(mode="json"),
            "fields": {"amount": str(trusted_amount)},
        }
        negotiation_id = f"neg_{uuid.uuid4().hex}"
        await self.db.persist_bare_metal_opening(
            negotiation_id=negotiation_id,
            listing_id=request.listing_id,
            seller_principal=self.seller_principal,
            buyer_agent_id=request.buyer_agent_url,
            buyer_principal=buyer_principal,
            seller_reference_amount=trusted_amount,
            strategy="bare_metal_hosted_exact",
            message=message,
            proposal=proposal_payload,
            buyer_amount=trusted_amount,
            seller_action="accept",
            seller_amount=trusted_amount,
            terms=terms,
            agreed_amount=trusted_amount,
        )
        await self.db.commit_settlement_plan(
            negotiation_id=negotiation_id,
            settlement_plan=plan.model_dump(mode="json"),
            buyer_principal=buyer_principal,
            seller_principal=self.seller_principal,
        )
        return NegotiateNewResponse(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=self.seller_principal,
            action="accept",
            proposal=proposal_payload,
            accepted_provision_terms=request.provision_terms,
            settlement_selection=selection,
            settlement_plan=plan,
        )
