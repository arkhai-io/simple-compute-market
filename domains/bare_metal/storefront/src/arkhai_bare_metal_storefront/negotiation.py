"""Deterministic seller negotiation policy for bare-metal leases."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from arkhai_bare_metal.schema import (
    SSH_ACCESS_METHOD,
    BareMetalListing,
    BareMetalMessage,
    BareMetalTerms,
)
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    run_negotiation_chain_with_context,
    their_last_proposal,
)
from market_policy.scalar_policies import (
    escrow_shape_guard,
    listed_price_middleware,
    proposal_uses_scalar_amount,
)
from market_policy.seller_round import SellerRoundResult


class BareMetalSellerRoundHook(Protocol):
    """Policy hook called with validated physical and commercial inputs."""

    async def __call__(
        self,
        *,
        listing: Mapping[str, Any] | BareMetalListing,
        message: Mapping[str, Any] | BareMetalMessage,
        history: list[NegotiationRound],
        seller_reference_amount: int,
        listing_ref: str | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult: ...


def _offer_resource(
    listing: Mapping[str, Any] | BareMetalListing,
) -> BareMetalListing:
    if isinstance(listing, BareMetalListing):
        return listing
    value: Any = listing.get("offer_resource", listing)
    if isinstance(value, str):
        value = json.loads(value)
    return BareMetalListing.model_validate(value)


def _listing_dict(
    listing: Mapping[str, Any] | BareMetalListing,
) -> dict[str, Any]:
    if isinstance(listing, BareMetalListing):
        return {"offer_resource": listing.model_dump(mode="json")}
    return dict(listing)


def _rejected_result(
    *,
    reason: str,
    seller_reference_amount: int,
    strategy_label: str,
    message: BareMetalMessage,
) -> SellerRoundResult:
    return SellerRoundResult(
        our_amount=seller_reference_amount,
        strategy_label=strategy_label,
        direction="maximize",
        chain_label="bare_metal_constraints",
        decision=NegotiationDecision(action="reject", reason=reason),
        intermediate={
            "bare_metal_message": message.model_dump(mode="json", exclude_none=True),
        },
    )


class _DefaultBareMetalSellerRoundHook:
    async def __call__(
        self,
        *,
        listing: Mapping[str, Any] | BareMetalListing,
        message: Mapping[str, Any] | BareMetalMessage,
        history: list[NegotiationRound],
        seller_reference_amount: int,
        listing_ref: str | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult:
        offer = _offer_resource(listing)
        requested = BareMetalMessage.model_validate(message)
        strategy = strategy_label or "bare_metal_listed_price"

        if (
            offer.min_duration_seconds is not None
            and requested.duration_seconds < offer.min_duration_seconds
        ):
            return _rejected_result(
                reason="bare_metal_duration_below_listing_min",
                seller_reference_amount=seller_reference_amount,
                strategy_label=strategy,
                message=requested,
            )
        if (
            offer.max_duration_seconds is not None
            and requested.duration_seconds > offer.max_duration_seconds
        ):
            return _rejected_result(
                reason="bare_metal_duration_above_listing_max",
                seller_reference_amount=seller_reference_amount,
                strategy_label=strategy,
                message=requested,
            )
        if requested.access_method not in offer.access_methods:
            return _rejected_result(
                reason="bare_metal_access_method_not_listed",
                seller_reference_amount=seller_reference_amount,
                strategy_label=strategy,
                message=requested,
            )
        if requested.access_method != SSH_ACCESS_METHOD:
            return _rejected_result(
                reason="bare_metal_access_method_unsupported",
                seller_reference_amount=seller_reference_amount,
                strategy_label=strategy,
                message=requested,
            )
        if requested.access_ref is not None:
            return _rejected_result(
                reason="bare_metal_buyer_access_ref_forbidden",
                seller_reference_amount=seller_reference_amount,
                strategy_label=strategy,
                message=requested,
            )
        if not (requested.ssh_public_key or "").strip():
            return _rejected_result(
                reason="bare_metal_ssh_public_key_required",
                seller_reference_amount=seller_reference_amount,
                strategy_label=strategy,
                message=requested,
            )

        terms = BareMetalTerms(
            machine_id=offer.machine_id,
            physical_host_id=offer.physical_host_id,
            duration_seconds=requested.duration_seconds,
            access_method=requested.access_method,
            ssh_public_key=requested.ssh_public_key,
            listing_ref=listing_ref,
        )
        listing_data = _listing_dict(listing)
        peer_proposal = their_last_proposal(history)
        uses_scalar_amount = proposal_uses_scalar_amount(
            listing_data,
            peer_proposal,
        )
        context = NegotiationContext(
            direction="maximize",
            our_reference_amount=float(seller_reference_amount),
            listing=listing_data,
            our_escrow_proposal=peer_proposal,
            intermediate={
                "uses_scalar_amount": uses_scalar_amount,
                "bare_metal_message": requested.model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                "bare_metal_terms": terms.model_dump(
                    mode="json",
                    exclude_none=True,
                ),
            },
        )
        decision, context = run_negotiation_chain_with_context(
            [escrow_shape_guard, listed_price_middleware],
            history,
            context,
        )
        return SellerRoundResult(
            our_amount=seller_reference_amount if uses_scalar_amount else 0,
            strategy_label=strategy,
            direction="maximize",
            chain_label="escrow_shape_guard,listed_price",
            decision=decision,
            intermediate=dict(context.intermediate),
        )


def default_seller_round_hook() -> BareMetalSellerRoundHook:
    """Build the deterministic default bare-metal seller policy."""
    return _DefaultBareMetalSellerRoundHook()
