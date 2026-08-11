"""VM-domain negotiation middlewares.

The middlewares that interpret VM market content: the round-zero duration guard
and the inventory guard. Both are offered to a composing role through
``arkhai_vms.negotiation.policy_sources``.

The alkahest-scalar vocabulary — bisection, listed_price, the escrow shape
guards, the per-kind dispatch — is escrow vocabulary rather than VM vocabulary
and lives in ``market_policy.scalar_policies``. Import it from there.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    NegotiationStep,
)
from market_policy.scalar_policies import (
    _amount_from_proposal,
    _is_round_zero,
    _loads_json_list,
    _peer_proposal,
    proposal_uses_scalar_amount,
)

logger = logging.getLogger(__name__)


def _coerce_resource_dict(value: Any) -> dict[str, Any]:
    import json

    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def round_zero_opening_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Validate and canonicalize VM opening-round negotiation content."""
    if not _is_round_zero(history):
        return None, context

    listing = context.listing or {}
    requested_duration_seconds = context.intermediate.get(
        "requested_duration_seconds",
    )
    if requested_duration_seconds is not None and int(requested_duration_seconds) <= 0:
        return (
            NegotiationDecision(
                action="reject",
                reason="compute_duration_invalid:duration_seconds must be > 0",
            ),
            context,
        )

    raw_listing_max_seconds = listing.get("max_duration_seconds")
    listing_max_seconds = (
        int(raw_listing_max_seconds)
        if raw_listing_max_seconds is not None and int(raw_listing_max_seconds) > 0
        else None
    )
    if (
        requested_duration_seconds is not None
        and listing_max_seconds is not None
        and int(requested_duration_seconds) > int(listing_max_seconds)
    ):
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"compute_duration_exceeds_listing_max:"
                    f"{requested_duration_seconds}>{listing_max_seconds}"
                ),
            ),
            context,
        )

    proposal = _peer_proposal(history)
    accepted = _loads_json_list(listing.get("accepted_escrows"))
    accepted_for_normalization = accepted if accepted else None
    accepted_proposal = None
    if isinstance(proposal, dict):
        try:
            from market_alkahest.schemas import (
                EscrowProposal,
                normalize_proposal_against_accepted_escrows,
            )

            accepted_proposal = normalize_proposal_against_accepted_escrows(
                proposal=EscrowProposal.model_validate(proposal),
                accepted_escrows=accepted_for_normalization,
            )
        except Exception as exc:
            return (
                NegotiationDecision(
                    action="reject",
                    reason=f"invalid_escrow_proposal:{exc}",
                ),
                context,
            )

    accepted_proposal_dict = (
        accepted_proposal.model_dump() if accepted_proposal is not None else None
    )
    if accepted_proposal_dict is not None:
        context.intermediate["accepted_escrow_proposal"] = accepted_proposal_dict

    proposal_for_scalar = (
        accepted_proposal_dict if accepted_proposal_dict is not None else proposal
    )
    uses_scalar_amount = proposal_uses_scalar_amount(listing, proposal_for_scalar)
    context.intermediate["uses_scalar_amount"] = uses_scalar_amount
    if uses_scalar_amount and _amount_from_proposal(proposal_for_scalar) is None:
        return (
            NegotiationDecision(
                action="reject",
                reason="missing_amount: buyer's escrow proposal has no fields.amount",
            ),
            context,
        )

    return None, context


def _row_is_available(row: Mapping[str, Any]) -> bool:
    """Whether an inventory row can serve a negotiation now.

    Two shapes reach this guard. A storefront-local resource row carries a
    ``state`` string. A site-authority projection carries no ``state`` at all — it
    reports ``enabled`` plus an ``available`` mapping of remaining capacity per
    dimension — and reading it with the local shape discarded every projected row
    before its attributes were examined, so the guard vetoed every negotiation on
    a correctly populated projection.

    A projected row with no ``available`` key is capacity whose remaining amount
    has not been reported, which is not the same as none: the fallback projection
    for a host with no registered capacity resource omits it. Treating unreported
    as unavailable would veto the deployment shape that sells today.
    """
    state = row.get("state")
    if state is not None:
        return str(state).strip() == "available"

    if row.get("enabled") is False:
        return False
    available = row.get("available")
    if available is None:
        return True
    if isinstance(available, Mapping):
        if not available:
            return True
        return any(_positive(amount) for amount in available.values())
    return bool(available)


def _positive(amount: Any) -> bool:
    try:
        return float(amount) > 0
    except (TypeError, ValueError):
        return False


def has_matching_inventory_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto when no available VM inventory resource matches the listing."""
    offer = _coerce_resource_dict(context.listing.get("offer_resource"))
    if "gpu_model" not in offer:
        return None, context

    required: dict[str, Any] = {}
    for key in ("region", "gpu_model"):
        v = offer.get(key)
        if v is not None:
            required[key] = v

    portfolio_raw = (context.available_resources or {}).get("resources") or []

    import json

    for row in portfolio_raw:
        if not _row_is_available(row):
            continue
        attrs = row.get("attributes")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except (ValueError, TypeError):
                continue
        if not isinstance(attrs, dict):
            continue
        if all(attrs.get(k) == v for k, v in required.items()):
            return None, context

    return (
        NegotiationDecision(action="reject", reason="no_matching_inventory"),
        context,
    )


__all__ = [
    "has_matching_inventory_guard",
    "round_zero_opening_guard",
]
