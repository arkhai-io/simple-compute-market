"""API-credit composition for the kit-owned negotiation lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from apicredits_storefront.services.capacity_client import (
    build_capacity_client,
    build_capacity_runtime,
    capacity_binding_from_offer,
)
from apicredits_storefront.services.keys_lookup import lookup_key_record
from apicredits_storefront.utils.config import CHAINS, settings
from domains.apicredits.listings.models import coerce_resource_dict
from domains.apicredits.listings.pricing import (
    determine_strategy_from_order,
    extract_unit_price_from_order,
)
from domains.apicredits.negotiation.storefront_round import ApiCreditsSellerRoundHook
from domains.apicredits.negotiation.terms import (
    provision_key_id,
    provision_key_mode,
    provision_quantity,
)
from market_alkahest.proposals import accepted_escrow_artifacts_from_proposal
from market_core import MarketDomainContract
from market_identity import Identity
from market_negotiation_runtime import (
    Acceptance,
    AgreementTerms,
    NegotiationDomainHooks,
    NegotiationRuntime,
    NegotiationStateError,
    NegotiationTerms,
    OpeningRecord,
    ResolvedNegotiation,
    RoundEvaluation,
    RoundRequest,
)
from market_policy.scalar_policies import _amount_from_proposal

logger = logging.getLogger(__name__)


def _negotiation_settings() -> Any:
    return settings.get("negotiation")


def _chain_settings() -> dict[str, Any]:
    return dict(CHAINS)


def _default_min_price() -> Any:
    return settings.get("pricing.default_min_price")


def _chain_config_paths() -> dict[str, str | None]:
    return {
        name: chain.alkahest_address_config_path for name, chain in CHAINS.items()
    }


def _seller_wallet_address() -> str | None:
    return str(settings.get("wallet.address", "") or "") or None


def _default_seller_round_hook(
    domain: MarketDomainContract,
    repository: Any,
) -> ApiCreditsSellerRoundHook:
    policy = domain.storefront
    if policy is None:
        raise RuntimeError(
            f"domain {domain.identity!s} has no storefront negotiation capability"
        )
    return policy.run_negotiation_policy(
        build_capacity_client(lambda: repository),
        lookup_key_record,
        negotiation_config=_negotiation_settings(),
        chains=_chain_settings(),
        default_min_price=_default_min_price(),
    )


def _decode_terms(domain: MarketDomainContract, raw_terms: Any) -> NegotiationTerms:
    if raw_terms is None:
        return NegotiationTerms(decoded=None, wire=None)
    raw = (
        raw_terms.model_dump(mode="json")
        if hasattr(raw_terms, "model_dump")
        else raw_terms
    )
    decoded = domain.codecs.message(raw)
    wire = (
        decoded.model_dump(mode="json")
        if hasattr(decoded, "model_dump")
        else dict(raw)
    )
    return NegotiationTerms(decoded=decoded, wire=wire)


def _validate_opening(
    _listing: Any,
    _listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
) -> None:
    if terms.decoded is None or provision_quantity(terms.decoded) is None:
        raise NegotiationStateError(
            "API-credit negotiation requires domain-valid provision terms"
        )


def _agreement(
    _listing: Any,
    _listing_record: Mapping[str, Any],
    _terms: NegotiationTerms,
) -> AgreementTerms:
    return AgreementTerms(0)


def _amount(proposal: Mapping[str, Any] | None) -> int | None:
    value = _amount_from_proposal(proposal)
    return int(value) if value is not None else None


def _proposal_from_amount(
    pinned: Mapping[str, Any] | None,
    amount: int | None,
) -> dict[str, Any] | None:
    if pinned is None and amount is None:
        return None
    base = dict(pinned) if pinned is not None else {}
    fields = base.get("fields")
    merged = dict(fields) if isinstance(fields, Mapping) else {}
    if amount is not None:
        merged["amount"] = int(amount)
    base["fields"] = merged
    return base


def _reference_amount(
    listing: Any,
    _listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
    uses_scalar_amount: bool,
) -> int:
    if not uses_scalar_amount:
        return 0
    unit = Decimal(
        str(
            extract_unit_price_from_order(
                listing,
                default_min_price=_default_min_price(),
            )
        )
    )
    quantity = provision_quantity(terms.decoded)
    return int(unit * int(quantity if quantity is not None else 1))


def build_api_credit_accepted_artifacts(
    *,
    buyer_principal: Identity,
    seller_principal: Identity,
    proposal: Any,
    agreed_amount: int,
    uses_scalar_amount: bool = True,
    duration_seconds: int = 0,
    **_unused: Any,
) -> dict[str, Any]:
    """Materialize the domain's durationless accepted settlement artifacts."""

    artifacts = accepted_escrow_artifacts_from_proposal(
        proposal=proposal,
        agreed_amount=agreed_amount,
        duration_seconds=duration_seconds,
        uses_scalar_amount=uses_scalar_amount,
        seller_wallet_address=_seller_wallet_address(),
        chain_config_paths=_chain_config_paths(),
        heartbeat_interval_seconds=None,
    )
    error = artifacts.pop("accepted_escrow_terms_error", None)
    if error:
        logger.debug("Could not materialize accepted escrow terms: %s", error)
    plan = artifacts.get("settlement_plan")
    if isinstance(plan, dict):
        buyer_wire = buyer_principal.model_dump(mode="json")
        seller_wire = seller_principal.model_dump(mode="json")
        plan["buyer_principal"] = buyer_wire
        plan["seller_principal"] = seller_wire
        for obligation in plan.get("obligations") or []:
            if isinstance(obligation, dict):
                obligation["payer_principal"] = buyer_wire
                obligation["claimant_principal"] = seller_wire
    return artifacts


def _build_response_artifacts(
    acceptance: Acceptance,
    accepted: bool,
) -> Mapping[str, Any]:
    artifacts = build_api_credit_accepted_artifacts(
        buyer_principal=acceptance.buyer_principal,
        seller_principal=acceptance.seller_principal,
        proposal=acceptance.pinned_proposal,
        agreed_amount=acceptance.agreed_amount,
        uses_scalar_amount=acceptance.uses_scalar_amount,
    )
    if accepted:
        return artifacts
    accepted_proposal = artifacts.get("accepted_escrow_proposal")
    return (
        {"accepted_escrow_proposal": accepted_proposal}
        if accepted_proposal is not None
        else {}
    )


async def _persist_opening(repository: Any, opening: OpeningRecord) -> None:
    quantity = provision_quantity(opening.terms.decoded)
    if quantity is None:
        return
    await repository.save_credit_terms(
        negotiation_id=opening.negotiation_id,
        quantity=int(quantity),
        key_mode=provision_key_mode(opening.terms.decoded),
        key_id=provision_key_id(opening.terms.decoded),
    )


async def _validate_continuation(
    repository: Any,
    _listing: Any,
    _listing_record: Mapping[str, Any],
    terms: NegotiationTerms,
    thread: Mapping[str, Any],
) -> None:
    negotiation_id = thread.get("negotiation_id")
    if not isinstance(negotiation_id, str) or not negotiation_id:
        raise NegotiationStateError("API-credit thread has no negotiation identity")
    recorded = await repository.load_credit_terms(negotiation_id=negotiation_id)
    quantity = provision_quantity(terms.decoded)
    key_mode = provision_key_mode(terms.decoded)
    key_id = provision_key_id(terms.decoded)
    if quantity is None:
        if recorded is not None:
            raise NegotiationStateError(
                "recorded API-credit terms do not match the negotiation transcript"
            )
        return
    if not recorded or (
        int(recorded.get("quantity", -1)),
        str(recorded.get("key_mode") or ""),
        recorded.get("key_id"),
    ) != (int(quantity), key_mode, key_id):
        raise NegotiationStateError(
            "recorded API-credit terms do not match the negotiation transcript"
        )


async def _place_quota_hold(
    repository: Any,
    acceptance: Acceptance,
) -> None:
    """Place the API-credit domain's best-effort quota hold after acceptance."""

    from core_storefront.stage_log import stage_event

    quantity = provision_quantity(acceptance.terms.decoded)
    ttl = float(settings.get("capacity.hold_ttl_seconds", 0) or 0)
    if ttl <= 0 or not quantity:
        return
    try:
        offer = coerce_resource_dict(acceptance.listing_record.get("offer_resource"))
        claim: dict[str, Any] = {
            "executor_kind": "api_credits",
            "units": int(quantity),
        }
        if offer.get("resource_id"):
            claim["resource_id"] = str(offer["resource_id"])
        capacity = build_capacity_runtime(lambda: repository)
        binding = capacity_binding_from_offer(offer)
        held = await capacity.reserve(
            binding,
            claim=claim,
            deal_ref={
                "listing_id": acceptance.listing_id,
                "negotiation_id": acceptance.negotiation_id,
            },
            ttl_seconds=ttl,
        )
    except Exception as exc:
        logger.warning(
            "[NEGOTIATION] Could not place quota hold for %s: %s",
            acceptance.negotiation_id,
            exc,
        )
        return
    if not held:
        stage_event(
            "negotiation",
            "capacity_hold_unavailable",
            negotiation_id=acceptance.negotiation_id,
            listing_id=acceptance.listing_id,
        )
        return
    await repository.save_capacity_hold(
        negotiation_id=acceptance.negotiation_id,
        listing_id=acceptance.listing_id,
        capacity_reservation_id=str(held["capacity_reservation_id"]),
        payload=held,
        expires_at=held.get("hold_expires_at"),
    )
    stage_event(
        "negotiation",
        "capacity_hold_placed",
        negotiation_id=acceptance.negotiation_id,
        listing_id=acceptance.listing_id,
        capacity_reservation_id=held.get("capacity_reservation_id"),
        resource_id=held.get("resource_id"),
        site=held.get("site"),
        hold_expires_at=held.get("hold_expires_at"),
    )


async def _persist_artifacts(
    repository: Any,
    acceptance: Acceptance,
    artifacts: Mapping[str, Any],
) -> None:
    plan = artifacts.get("settlement_plan")
    if isinstance(plan, dict):
        await repository.commit_settlement_plan(
            negotiation_id=acceptance.negotiation_id,
            settlement_plan=plan,
            buyer_principal=acceptance.buyer_principal,
            seller_principal=acceptance.seller_principal,
        )


def build_api_credit_negotiation_runtime(
    domain: MarketDomainContract,
    *,
    seller_round_hook: ApiCreditsSellerRoundHook | None = None,
) -> NegotiationRuntime:
    """Compose the shared lifecycle with API-credit codecs and effects."""

    async def resolve_opening(
        repository: Any,
        listing_id: str,
    ) -> ResolvedNegotiation:
        record = await repository.load_listing(listing_id=listing_id)
        if not record:
            raise NegotiationStateError(
                f"Order {listing_id} not found locally; seller has no matching listing"
            )
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=record,
            listing_record=record,
            hooks=hooks,
        )

    async def resolve_continuation(
        repository: Any,
        thread: Mapping[str, Any],
    ) -> ResolvedNegotiation:
        listing_id = thread.get("our_listing_id")
        if not isinstance(listing_id, str) or not listing_id:
            raise NegotiationStateError(
                "negotiation has no recorded API-credit listing"
            )
        record = await repository.load_listing(listing_id=listing_id)
        if not record:
            raise NegotiationStateError(
                f"Seller's order {listing_id} is gone from local DB"
            )
        return ResolvedNegotiation(
            listing_id=listing_id,
            listing=record,
            listing_record=record,
            hooks=hooks,
        )

    async def evaluate(request: RoundRequest) -> RoundEvaluation:
        policy = seller_round_hook or _default_seller_round_hook(
            domain,
            request.repository,
        )
        decoded = request.terms.decoded
        result = await policy(
            listing=request.listing,
            history=list(request.history),
            requested_quantity=provision_quantity(decoded),
            key_mode=provision_key_mode(decoded),
            key_id=provision_key_id(decoded),
            buyer_principal=request.buyer_principal,
            **(
                {"strategy_label": request.strategy_label}
                if request.strategy_label is not None
                else {}
            ),
        )
        state = result.intermediate or {}
        pinned = state.get("accepted_escrow_proposal")
        return RoundEvaluation(
            our_amount=int(result.our_amount),
            strategy_label=result.strategy_label,
            decision=result.decision,
            pinned_proposal=(dict(pinned) if isinstance(pinned, Mapping) else None),
            uses_scalar_amount=bool(state.get("uses_scalar_amount", True)),
            buyer_amount=(
                int(state["buyer_amount"])
                if state.get("buyer_amount") is not None
                else None
            ),
            domain_state=state,
        )

    async def listing_is_paused(repository: Any, listing_id: str) -> bool:
        return bool(await repository.is_listing_paused(listing_id=listing_id))

    def storefront_is_paused() -> bool:
        from apicredits_storefront.server import is_globally_paused

        return bool(is_globally_paused())

    from core_storefront.stage_log import stage_event

    hooks = NegotiationDomainHooks(
        decode_terms=lambda raw: _decode_terms(domain, raw),
        validate_opening=_validate_opening,
        validate_continuation=_validate_continuation,
        evaluate_round=evaluate,
        determine_strategy=lambda listing, _record: determine_strategy_from_order(
            listing
        ),
        reference_amount=_reference_amount,
        amount_from_proposal=_amount,
        proposal_from_amount=_proposal_from_amount,
        agreement_terms=_agreement,
        build_artifacts=_build_response_artifacts,
        decision_wire=lambda decision: decision.to_dict(),
        listing_is_live=lambda record: str(record.get("status") or "").strip()
        == "open",
        listing_is_paused=listing_is_paused,
        storefront_is_paused=storefront_is_paused,
        stage_event=stage_event,
        persist_opening=_persist_opening,
        place_hold=_place_quota_hold,
        persist_artifacts=_persist_artifacts,
    )
    return NegotiationRuntime(
        resolve_opening=resolve_opening,
        resolve_continuation=resolve_continuation,
    )
