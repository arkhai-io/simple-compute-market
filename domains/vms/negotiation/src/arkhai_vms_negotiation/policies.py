"""VM-domain negotiation middlewares.

The alkahest-scalar vocabulary (bisection, listed_price, the escrow
shape guards, the per-kind dispatch) moved to
``market_policy.scalar_policies`` — it is escrow vocabulary, not VM
vocabulary — and is re-exported here so existing import paths keep
working. This module keeps the middlewares that interpret VM market
content, such as the round-zero duration guard. The inventory guard is
domain-neutral and lives in ``market_policy.listing_source``.
"""

from __future__ import annotations

import logging
import re

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    NegotiationStep,
    register_negotiation_middleware,
)
from market_policy.scalar_policies import (  # noqa: F401 — re-exports
    DEFAULT_CONVERGENCE_RATIO,
    DEFAULT_REASONABLE_MULTIPLIER,
    _ZERO_ADDRESS,
    _accepted_entry_uses_scalar_amount,
    _accepted_escrow_for_proposal,
    _amount_from_proposal,
    _escrow_kind_lookup_keys,
    _is_round_zero,
    _loads_json_list,
    _normalize_demands_for_chain,
    _normalize_escrow_field,
    _normalize_exact_value,
    _normalize_rate,
    _opening_amount,
    _opening_proposal,
    _peer_proposal,
    _proposal_requires_exact_amount,
    _set_proposal_amount,
    format_wire_amount,
    parse_wire_amount,
    accept_exact_listing_middleware,
    amount_bisection_middleware,
    bisection_middleware,
    buyer_counter_guard,
    buyer_escrow_shape_guard,
    escrow_shape_guard,
    escrow_shape_uses_scalar_amount,
    listed_price_middleware,
    make_escrow_kind_dispatch_middleware,
    our_first_proposal,
    our_previous_counters,
    proposal_escrow_kind,
    proposal_uses_scalar_amount,
    their_proposed_amount,
)

logger = logging.getLogger(__name__)


@register_negotiation_middleware("round_zero_opening_guard")
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
    accepted_proposal_dict = None
    if isinstance(proposal, dict) and proposal.get("settlement_selection") is not None:
        try:
            selection = proposal["settlement_selection"]
            # A selection names its option exactly; `params` carries the buyer's
            # inputs to the mechanism (a payer account, say) and is optional.
            if (
                not isinstance(selection, dict)
                or not {"mechanism", "option_id", "expiration_unix"}.issubset(selection)
                or set(selection) - {"mechanism", "option_id", "expiration_unix", "params"}
                or (selection.get("params") is not None and not isinstance(selection["params"], dict))
            ):
                raise ValueError("selection has invalid fields")
            mechanism = selection["mechanism"]
            option_id = selection["option_id"]
            expiration_unix = selection["expiration_unix"]
            if not isinstance(mechanism, str) or not mechanism:
                raise ValueError("selection mechanism is required")
            if (
                not isinstance(option_id, str)
                or re.fullmatch(r"[0-9a-f]{64}", option_id) is None
            ):
                raise ValueError("selection option_id is invalid")
            if (
                isinstance(expiration_unix, bool)
                or not isinstance(expiration_unix, int)
                or expiration_unix <= 0
            ):
                raise ValueError("selection expiration is invalid")
            options = _loads_json_list(listing.get("settlement_options"))
            matched = next(
                (
                    option
                    for option in options
                    if isinstance(option, dict)
                    and option.get("option_id") == option_id
                    and option.get("mechanism") == mechanism
                ),
                None,
            )
            if matched is None:
                raise ValueError("selection does not exact-match a listing option")
            context.intermediate["accepted_settlement_selection"] = dict(selection)
            context.intermediate["accepted_settlement_option"] = matched
        except Exception as exc:
            return (
                NegotiationDecision(
                    action="reject",
                    reason=f"invalid_settlement_selection:{exc}",
                ),
                context,
            )
    else:
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


__all__ = [
    "_amount_from_proposal",
    "format_wire_amount",
    "parse_wire_amount",
    "accept_exact_listing_middleware",
    "amount_bisection_middleware",
    "bisection_middleware",
    "buyer_counter_guard",
    "buyer_escrow_shape_guard",
    "escrow_shape_guard",
    "make_escrow_kind_dispatch_middleware",
    "our_first_proposal",
    "our_previous_counters",
    "proposal_escrow_kind",
    "proposal_uses_scalar_amount",
    "round_zero_opening_guard",
    "their_proposed_amount",
]


def _backfill_market_policy_compat_exports() -> None:
    import market_policy.negotiation_middleware as compat

    for name in __all__:
        setattr(compat, name, globals()[name])


_backfill_market_policy_compat_exports()
