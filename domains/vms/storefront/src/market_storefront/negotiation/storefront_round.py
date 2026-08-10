"""VM storefront seller-round hook implementation."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from market_policy import NegotiationCatalogue
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationMiddleware,
    NegotiationRound,
    normalize_policies_by_escrow_kind_config,
    run_negotiation_chain_with_context,
)
from market_policy.scalar_policies import (
    make_escrow_kind_dispatch_middleware,
    proposal_uses_scalar_amount,
)

from market_storefront.listings import (
    determine_strategy_from_order,
    extract_initial_price_from_order,
)

logger = logging.getLogger(__name__)


# The result carrier and hook protocol are domain-invariant and live in
# the policy kit; re-exported here so existing import paths keep working.
from market_policy.seller_round import (
    SellerRoundHook,
    SellerRoundResult,
)


async def _default_seller_policy_inputs(capacity: Any) -> dict[str, Any]:
    """Advisory availability snapshot for the inventory guard.

    ``capacity`` is a site-authority capacity client (anything with an
    async ``snapshot()`` returning resource rows) — duck-typed so this
    concept module needs no core import.
    """
    return {
        "available_resources": {
            "resources": await capacity.snapshot() or [],
        },
    }


_DEFAULT_GUARDS = [
    "round_zero_opening_guard",
    "buyer_counter_guard",
    "has_matching_inventory_guard",
    "escrow_shape_guard",
]
_DEFAULT_TERMINAL = "bisection"


def _prepend_default_guards(policy_names: list[str]) -> list[str]:
    out = list(policy_names)
    for guard in reversed(_DEFAULT_GUARDS):
        if guard not in out:
            out.insert(0, guard)
    return out


def _load_storefront_chain(
    *,
    policy_catalogue: NegotiationCatalogue,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
) -> list[NegotiationMiddleware]:
    """Resolve the VM storefront's configured negotiation middleware chain.

    Names resolve against the catalogue the composing role built. Operator
    directory discovery and the torch strategy are no longer triggered from
    here: both are sources the role authorizes at composition, so a chain
    cannot cause a mechanism to be consulted mid-negotiation.
    """
    negotiation_cfg = negotiation_config
    raw_policies = getattr(negotiation_cfg, "policies", None)
    policies_by_kind = normalize_policies_by_escrow_kind_config(raw_policies)
    if policies_by_kind:
        chain_config_paths = {
            name: chain.alkahest_address_config_path
            for name, chain in (chains or {}).items()
        }
        return policy_catalogue.resolve(_DEFAULT_GUARDS) + [
            make_escrow_kind_dispatch_middleware(
                policies_by_kind,
                resolve=policy_catalogue.resolve,
                chain_config_paths=chain_config_paths,
            )
        ]

    policy_names = list(raw_policies or [])
    if not policy_names:
        policy_mode = (
            getattr(negotiation_cfg, "policy_mode", "") or ""
        ).strip() or _DEFAULT_TERMINAL
        policy_names = [policy_mode]
    policy_names = _prepend_default_guards(policy_names)

    return policy_catalogue.resolve(policy_names)


def _direction_from_strategy_label(strategy: str) -> str:
    if strategy in ("minimize", "maximize"):
        return strategy
    raise ValueError(f"Unknown order strategy {strategy!r}")


def _seller_reference_amount(
    listing: Any,
    duration_seconds: int | None,
    *,
    default_min_price: Any = None,
) -> int:
    """Compute the seller's absolute reference amount in base units."""
    per_hour = Decimal(
        str(
            extract_initial_price_from_order(
                listing,
                default_min_price=default_min_price,
            )
        )
    )
    seconds = int(duration_seconds) if duration_seconds is not None else 3600
    return int(per_hour * seconds // Decimal(3600))


async def _run_default_seller_round_policy(
    *,
    listing: Any,
    history: list[NegotiationRound],
    requested_duration_seconds: int | None = None,
    strategy_label: str | None = None,
    policy_inputs: dict[str, Any] | None = None,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
    policy_catalogue: NegotiationCatalogue,
    default_min_price: Any = None,
) -> SellerRoundResult:
    """Run the default VM seller per-round policy hook."""
    from arkhai_vms.listing_models import Listing

    if not strategy_label:
        strategy_label = determine_strategy_from_order(listing)
    if not strategy_label:
        raise ValueError(
            f"Listing {getattr(listing, 'listing_id', repr(listing))} "
            "has no usable strategy for negotiation"
        )

    listing_dict = (
        listing.model_dump(mode="json") if isinstance(listing, Listing) else listing
    )
    their_proposal = None
    for item in reversed(history):
        if item.sender == "them":
            their_proposal = item.proposal
            break
    uses_scalar_amount = proposal_uses_scalar_amount(
        listing_dict if isinstance(listing_dict, dict) else {},
        their_proposal,
    )
    reference_amount = (
        _seller_reference_amount(
            listing,
            requested_duration_seconds,
            default_min_price=default_min_price,
        )
        if uses_scalar_amount
        else 0
    )
    direction = _direction_from_strategy_label(strategy_label)

    chain = _load_storefront_chain(
        negotiation_config=negotiation_config,
        chains=chains,
        policy_catalogue=policy_catalogue,
    )
    context = NegotiationContext(
        direction=direction,
        our_reference_amount=float(reference_amount),
        listing=listing_dict if isinstance(listing_dict, dict) else {},
        our_escrow_proposal=their_proposal,
        available_resources=(
            (policy_inputs or {}).get("available_resources") or {"resources": []}
        ),
        intermediate={
            "requested_duration_seconds": requested_duration_seconds,
            "seller_reference_amount": int(reference_amount),
            "uses_scalar_amount": uses_scalar_amount,
        },
    )
    decision, context = run_negotiation_chain_with_context(chain, history, context)
    chain_label = ",".join(
        type(mw).__name__ if not hasattr(mw, "__name__") else mw.__name__
        for mw in chain
    )
    uses_scalar_amount = context.intermediate.get("uses_scalar_amount", True)
    return SellerRoundResult(
        our_amount=int(reference_amount) if uses_scalar_amount else 0,
        strategy_label=strategy_label,
        direction=direction,
        chain_label=chain_label,
        decision=decision,
        intermediate=dict(context.intermediate),
    )


@dataclass
class _DefaultSellerRoundHook:
    capacity: Any
    negotiation_config: Any = None
    chains: Mapping[str, Any] | None = None
    policy_catalogue: NegotiationCatalogue | None = None
    default_min_price: Any = None

    async def __call__(
        self,
        *,
        listing: Any,
        history: list[NegotiationRound],
        requested_duration_seconds: int | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult:
        policy_inputs = await _default_seller_policy_inputs(self.capacity)
        return await _run_default_seller_round_policy(
            listing=listing,
            history=history,
            requested_duration_seconds=requested_duration_seconds,
            strategy_label=strategy_label,
            policy_inputs=policy_inputs,
            negotiation_config=self.negotiation_config,
            chains=self.chains,
            policy_catalogue=self.policy_catalogue,
            default_min_price=self.default_min_price,
        )


def default_seller_round_hook(
    capacity: Any,
    *,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
    policy_catalogue: NegotiationCatalogue,
    default_min_price: Any = None,
) -> SellerRoundHook:
    """Build the default VM seller round hook.

    ``capacity`` provides the round-start availability snapshot
    (site-authority capacity client; ``snapshot()`` feeds the inventory
    guard's ``available_resources`` input).
    """
    return _DefaultSellerRoundHook(
        capacity=capacity,
        negotiation_config=negotiation_config,
        chains=chains,
        policy_catalogue=policy_catalogue,
        default_min_price=default_min_price,
    )
