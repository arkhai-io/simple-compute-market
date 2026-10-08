"""Seller negotiation policy for bare-metal leases.

The domain's own checks (duration bounds, access method, SSH key, no
buyer-supplied access authority) run first and refuse for their own reasons;
then a configured chain decides the price. The chain always begins with
``has_matching_inventory_guard``, which reads the negotiation runtime's check of
the listing against its source for the round. The default chain accepts at or
above the listed rate and exits below it; a chain ending in ``bisection``
counters.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from arkhai_bare_metal.schema import (
    SSH_ACCESS_METHOD,
    BareMetalListing,
    BareMetalMessage,
    BareMetalTerms,
)
from market_policy.listing_source import ListingSourceVerdict
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationMiddleware,
    NegotiationRound,
    load_negotiation_chain,
    normalize_policy_chain_config,
    run_negotiation_chain_with_context,
    their_last_proposal,
)
from market_policy.scalar_policies import proposal_uses_scalar_amount
from market_policy.seller_round import SellerRoundResult

#: The seller chain when none is configured: the escrow shape, then the listed rate.
DEFAULT_SELLER_POLICIES: tuple[str, ...] = ("escrow_shape_guard", "listed_price")
#: Prepended to every chain, so no configuration can drop the source check.
REQUIRED_SELLER_GUARDS: tuple[str, ...] = ("has_matching_inventory_guard",)


def seller_policy_names(configured: Any = None) -> list[str]:
    """The seller chain's middleware names: the required guards, then ``configured``.

    ``configured`` is any form the policy kit normalizes (a name, a list, or a
    mapping naming a chain); nothing configured means the default chain.
    """
    names = normalize_policy_chain_config(configured) or list(DEFAULT_SELLER_POLICIES)
    return [
        *REQUIRED_SELLER_GUARDS,
        *(name for name in names if name not in REQUIRED_SELLER_GUARDS),
    ]


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
        listing_source: ListingSourceVerdict | None = None,
    ) -> SellerRoundResult: ...


def _listing_resource(
    listing: Mapping[str, Any] | BareMetalListing,
) -> BareMetalListing:
    if isinstance(listing, BareMetalListing):
        return listing
    value: Any = listing.get("listing_resource", listing)
    if isinstance(value, str):
        value = json.loads(value)
    return BareMetalListing.model_validate(value)


def _listing_dict(
    listing: Mapping[str, Any] | BareMetalListing,
) -> dict[str, Any]:
    if isinstance(listing, BareMetalListing):
        return {"listing_resource": listing.model_dump(mode="json")}
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


def bare_metal_admission_refusal(
    listing: BareMetalListing, requested: BareMetalMessage
) -> str | None:
    """Why a request for this listed machine cannot be accepted, or None.

    Every deal that provisions the machine is held to these, however it is
    settled: the duration within the listing's bounds, SSH access the listing
    advertises, a buyer key, and no buyer-supplied access authority.
    """

    if (
        listing.min_duration_seconds is not None
        and requested.duration_seconds < listing.min_duration_seconds
    ):
        return "bare_metal_duration_below_listing_min"
    if (
        listing.max_duration_seconds is not None
        and requested.duration_seconds > listing.max_duration_seconds
    ):
        return "bare_metal_duration_above_listing_max"
    if requested.access_method not in listing.access_methods:
        return "bare_metal_access_method_not_listed"
    if requested.access_method != SSH_ACCESS_METHOD:
        return "bare_metal_access_method_unsupported"
    if requested.access_ref is not None:
        return "bare_metal_buyer_access_ref_forbidden"
    if not (requested.ssh_public_key or "").strip():
        return "bare_metal_ssh_public_key_required"
    return None


class _DefaultBareMetalSellerRoundHook:
    def __init__(self, names: Sequence[str]) -> None:
        self._names = list(names)
        self._chain: list[NegotiationMiddleware] = load_negotiation_chain(self._names)

    async def __call__(
        self,
        *,
        listing: Mapping[str, Any] | BareMetalListing,
        message: Mapping[str, Any] | BareMetalMessage,
        history: list[NegotiationRound],
        seller_reference_amount: int,
        listing_ref: str | None = None,
        strategy_label: str | None = None,
        listing_source: ListingSourceVerdict | None = None,
    ) -> SellerRoundResult:
        listing_resource = _listing_resource(listing)
        requested = BareMetalMessage.model_validate(message)
        strategy = strategy_label or "bare_metal_listed_price"

        refusal = bare_metal_admission_refusal(listing_resource, requested)
        if refusal is not None:
            return _rejected_result(
                reason=refusal,
                seller_reference_amount=seller_reference_amount,
                strategy_label=strategy,
                message=requested,
            )

        terms = BareMetalTerms(
            host_id=listing_resource.host_id,
            physical_host_id=listing_resource.physical_host_id,
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
            our_reference_amount=int(seller_reference_amount),
            listing=listing_data,
            our_escrow_proposal=peer_proposal,
            listing_source=listing_source,
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
            self._chain,
            history,
            context,
        )
        return SellerRoundResult(
            our_amount=seller_reference_amount if uses_scalar_amount else 0,
            strategy_label=strategy,
            direction="maximize",
            chain_label=",".join(self._names),
            decision=decision,
            intermediate=dict(context.intermediate),
        )


def default_seller_round_hook(policies: Any = None) -> BareMetalSellerRoundHook:
    """Build the bare-metal seller policy over the configured chain.

    ``policies`` names the chain after the required guards; ``None`` selects the
    default. An unknown name is refused here, when the storefront is composed.
    """
    return _DefaultBareMetalSellerRoundHook(seller_policy_names(policies))
