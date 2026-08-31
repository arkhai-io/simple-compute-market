"""API-credits storefront seller-round hook.

Mirrors the VM domain's ``storefront_round`` at the same altitude: the
hook captures the round's side inputs (quota snapshot, key→owner
lookup), computes the seller's absolute reference amount — here
``quantity × unit rate``, the per-unit→absolute translation living in
the domain's policy seam — and runs the configured middleware chain.

``SellerRoundResult`` is the domain-invariant carrier from
``market_policy.seller_round``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping, Protocol

from market_identity import Identity
import domains.apicredits.negotiation.policies  # noqa: F401 — registers the guards
from domains.apicredits.listings.pricing import (
    checked_credit_total,
    determine_strategy_from_order,
    extract_unit_price_from_order,
)
from market_policy.scalar_policies import (
    make_escrow_kind_dispatch_middleware,
    proposal_uses_scalar_amount,
)
from market_policy.seller_round import SellerRoundResult
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationMiddleware,
    NegotiationRound,
    load_negotiation_chain,
    normalize_policies_by_escrow_kind_config,
    run_negotiation_chain_with_context,
)

logger = logging.getLogger(__name__)

KeyLookup = Callable[[str], Awaitable[dict[str, Any] | None]]
"""Resolve a key_id to its credits-service record (owner claim, status),
or None when unknown. Captured once per round, like the snapshot."""


_DEFAULT_GUARDS = [
    "api_credits_round_zero_guard",
    "buyer_counter_guard",
    "credit_quota_guard",
    "key_owned_by_buyer_principal",
    "escrow_shape_guard",
]
_DEFAULT_TERMINAL = "listed_price"


class ApiCreditsSellerRoundHook(Protocol):
    async def __call__(
        self,
        *,
        listing: Mapping[str, Any],
        history: list[NegotiationRound],
        buyer_principal: Identity,
        requested_quantity: int | None = None,
        key_mode: str | None = None,
        key_id: str | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult: ...


def _load_chain(
    *,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
) -> list[NegotiationMiddleware]:
    """Resolve the API-credits storefront's negotiation middleware chain.

    Same configuration vocabulary as the VM storefront: a flat
    ``policies`` list, a ``policy_mode`` terminal default, or a
    per-escrow-kind dispatch table. (File-policy discovery and the RL
    strategies are VM-storefront features this domain doesn't ship.)
    """
    raw_policies = getattr(negotiation_config, "policies", None)
    policies_by_kind = normalize_policies_by_escrow_kind_config(raw_policies)
    if policies_by_kind:
        chain_config_paths = {
            name: chain.alkahest_address_config_path
            for name, chain in (chains or {}).items()
        }
        return load_negotiation_chain(_DEFAULT_GUARDS) + [
            make_escrow_kind_dispatch_middleware(
                policies_by_kind,
                chain_config_paths=chain_config_paths,
            )
        ]

    policy_names = list(raw_policies or [])
    if not policy_names:
        policy_mode = (
            getattr(negotiation_config, "policy_mode", "") or ""
        ).strip() or _DEFAULT_TERMINAL
        policy_names = [policy_mode]
    for guard in reversed(_DEFAULT_GUARDS):
        if guard not in policy_names:
            policy_names.insert(0, guard)
    return load_negotiation_chain(policy_names)


def _seller_reference_amount(
    listing: Mapping[str, Any],
    quantity: int | None,
    *,
    default_min_price: Any = None,
    settlement_selection: Mapping[str, Any] | None = None,
) -> int:
    """quantity × exact selected per-credit rate, in base units."""
    unit = extract_unit_price_from_order(
        dict(listing),
        default_min_price=default_min_price,
        settlement_selection=(
            dict(settlement_selection) if settlement_selection is not None else None
        ),
    )
    count = int(quantity) if quantity is not None else 1
    if settlement_selection is not None:
        return checked_credit_total(unit, count)
    return int(Decimal(str(unit)) * count)


async def _run_seller_round(
    *,
    listing: Mapping[str, Any],
    history: list[NegotiationRound],
    requested_quantity: int | None,
    key_mode: str | None,
    key_id: str | None,
    buyer_principal: Identity,
    strategy_label: str | None,
    policy_inputs: dict[str, Any],
    negotiation_config: Any,
    chains: Mapping[str, Any] | None,
    default_min_price: Any,
) -> SellerRoundResult:
    listing_dict = dict(listing)
    if not strategy_label:
        strategy_label = determine_strategy_from_order(listing_dict)
    if not strategy_label:
        raise ValueError(
            f"Listing {listing_dict.get('listing_id')!r} has no usable "
            "strategy for negotiation"
        )

    their_proposal = None
    for item in reversed(history):
        if item.sender == "them":
            their_proposal = item.proposal
            break
    settlement_selection = (
        their_proposal.get("settlement_selection")
        if isinstance(their_proposal, Mapping)
        and isinstance(their_proposal.get("settlement_selection"), Mapping)
        else None
    )
    uses_scalar_amount = proposal_uses_scalar_amount(listing_dict, their_proposal)
    reference_amount = (
        _seller_reference_amount(
            listing_dict,
            requested_quantity,
            default_min_price=default_min_price,
            settlement_selection=settlement_selection,
        )
        if uses_scalar_amount
        else 0
    )

    chain = _load_chain(negotiation_config=negotiation_config, chains=chains)
    context = NegotiationContext(
        direction="maximize",
        our_reference_amount=float(reference_amount),
        listing=listing_dict,
        our_escrow_proposal=their_proposal,
        available_resources=policy_inputs.get("available_resources")
        or {"resources": []},
        intermediate={
            "requested_quantity": requested_quantity,
            "key_mode": key_mode or "new",
            "key_id": key_id,
            "key_record": policy_inputs.get("key_record"),
            "buyer_principal": buyer_principal.model_dump(mode="json"),
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
        direction="maximize",
        chain_label=chain_label,
        decision=decision,
        intermediate=dict(context.intermediate),
    )


class _DefaultSellerRoundHook:
    def __init__(
        self,
        capacity: Any,
        key_lookup: KeyLookup | None,
        *,
        negotiation_config: Any = None,
        chains: Mapping[str, Any] | None = None,
        default_min_price: Any = None,
    ) -> None:
        self._capacity = capacity
        self._key_lookup = key_lookup
        self._negotiation_config = negotiation_config
        self._chains = chains
        self._default_min_price = default_min_price

    async def __call__(
        self,
        *,
        listing: Mapping[str, Any],
        history: list[NegotiationRound],
        buyer_principal: Identity,
        requested_quantity: int | None = None,
        key_mode: str | None = None,
        key_id: str | None = None,
        strategy_label: str | None = None,
    ) -> SellerRoundResult:
        policy_inputs: dict[str, Any] = {
            "available_resources": {
                "resources": await self._capacity.snapshot() or [],
            },
        }
        if (key_mode or "new") == "existing" and key_id and self._key_lookup:
            try:
                policy_inputs["key_record"] = await self._key_lookup(key_id)
            except Exception as exc:
                # An unreachable credits service must not admit unverified
                # claims — the guard sees no record and rejects early;
                # issuance would have re-checked (and failed) anyway.
                logger.warning(
                    "[NEGOTIATION] key lookup failed for %r: %s",
                    key_id,
                    exc,
                )
                policy_inputs["key_record"] = None
        return await _run_seller_round(
            listing=listing,
            history=history,
            requested_quantity=requested_quantity,
            key_mode=key_mode,
            key_id=key_id,
            buyer_principal=buyer_principal,
            strategy_label=strategy_label,
            policy_inputs=policy_inputs,
            negotiation_config=self._negotiation_config,
            chains=self._chains,
            default_min_price=self._default_min_price,
        )


def default_seller_round_hook(
    capacity: Any,
    key_lookup: KeyLookup | None = None,
    *,
    negotiation_config: Any = None,
    chains: Mapping[str, Any] | None = None,
    default_min_price: Any = None,
) -> ApiCreditsSellerRoundHook:
    """Build the default API-credits seller round hook.

    ``capacity`` provides the quota snapshot for ``credit_quota_guard``;
    ``key_lookup`` provides the key→owner record for
    ``key_owned_by_buyer_principal`` (both captured per round — the chain
    itself stays synchronous and side-effect free).
    """
    return _DefaultSellerRoundHook(
        capacity,
        key_lookup,
        negotiation_config=negotiation_config,
        chains=chains,
        default_min_price=default_min_price,
    )
