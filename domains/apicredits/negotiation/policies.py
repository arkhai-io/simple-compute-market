"""API-credits negotiation middlewares.

The scalar/escrow vocabulary (bisection, listed_price, escrow shape
guards, escrow-kind dispatch, the buyer counter guard) is shared with
the VM domain and lives in ``market_policy.scalar_policies``.
Importing that module also registers them, so an apicredits chain can
name them directly.

This module owns what is genuinely API-credits vocabulary:

* ``api_credits_round_zero_guard`` — validates and canonicalizes the
  opening round (quantity ≥ 1, proposal normalized against the
  listing's acceptance set, scalar amount present).
* ``credit_quota_guard`` — the inventory-guard analog: requested
  quantity ≤ the quota resource's available units in the captured
  capacity snapshot. Advisory, like every negotiation-time check —
  issuance re-reserves authoritatively.
* ``key_owned_by_buyer_principal`` — the seller-default ownership guard:
  for an existing-key claim, the captured key record's canonical owner
  must equal the authenticated negotiation principal. The guard is
  advisory; issuance repeats the exact-principal check authoritatively.
"""

from __future__ import annotations

import logging
import re

from market_identity import Identity, IdentityScheme
from market_alkahest.schemas import (
    EscrowProposal,
    normalize_proposal_against_accepted_escrows,
)
from domains.apicredits.listings.models import coerce_resource_dict
from market_policy.scalar_policies import (  # shared alkahest-scalar vocabulary
    _amount_from_proposal,
    _loads_json_list,
    proposal_uses_scalar_amount,
)
from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    NegotiationStep,
    register_negotiation_middleware,
    their_last_proposal,
)

logger = logging.getLogger(__name__)

# Reject vocabulary shared with the credits service (the service's
# issuance re-check uses the same names).
KEY_NOT_FOUND = "key_not_found"
KEY_NOT_OWNED = "key_not_owned"
KEY_REVOKED = "key_revoked"
QUOTA_EXHAUSTED = "quota_exhausted"


def _is_round_zero(history: list[NegotiationRound]) -> bool:
    return (
        len(history) == 1
        and history[0].round_number == 0
        and history[0].sender == "them"
        and history[0].action == "initial"
    )


@register_negotiation_middleware("api_credits_round_zero_guard")
def api_credits_round_zero_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Validate and canonicalize the API-credits opening round."""
    if not _is_round_zero(history):
        return None, context

    listing = context.listing or {}
    quantity = context.intermediate.get("requested_quantity")
    if quantity is None:
        return (
            NegotiationDecision(
                action="reject",
                reason="credit_quantity_missing: provision_terms.payload.quantity is required",
            ),
            context,
        )
    if int(quantity) < 1:
        return (
            NegotiationDecision(
                action="reject",
                reason="credit_quantity_invalid: quantity must be >= 1",
            ),
            context,
        )

    key_mode = context.intermediate.get("key_mode") or "new"
    if key_mode not in ("new", "existing"):
        return (
            NegotiationDecision(
                action="reject",
                reason=f"key_disposition_invalid: mode {key_mode!r}",
            ),
            context,
        )
    if key_mode == "existing" and not context.intermediate.get("key_id"):
        return (
            NegotiationDecision(
                action="reject",
                reason="key_disposition_invalid: existing mode requires key_id",
            ),
            context,
        )

    proposal = their_last_proposal(history)
    accepted_proposal_dict = None
    if isinstance(proposal, dict) and proposal.get("settlement_selection") is not None:
        try:
            selection = proposal["settlement_selection"]
            if not isinstance(selection, dict) or set(selection) != {
                "mechanism",
                "option_id",
                "expiration_unix",
            }:
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
            matches = [
                option
                for option in options
                if isinstance(option, dict)
                and option.get("option_id") == option_id
                and option.get("mechanism") == mechanism
            ]
            if len(matches) != 1:
                raise ValueError("selection does not exact-match one listing option")
            context.intermediate["accepted_settlement_selection"] = dict(selection)
            context.intermediate["accepted_settlement_option"] = matches[0]
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
        if isinstance(proposal, dict):
            try:
                accepted_proposal = normalize_proposal_against_accepted_escrows(
                    proposal=EscrowProposal.model_validate(proposal),
                    accepted_escrows=accepted if accepted else None,
                )
                accepted_proposal_dict = accepted_proposal.model_dump()
            except Exception as exc:
                return (
                    NegotiationDecision(
                        action="reject",
                        reason=f"invalid_escrow_proposal:{exc}",
                    ),
                    context,
                )

        if accepted_proposal_dict is not None:
            context.intermediate["accepted_escrow_proposal"] = accepted_proposal_dict

    proposal_for_scalar = (
        proposal
        if context.intermediate.get("accepted_settlement_selection") is not None
        else accepted_proposal_dict
        if accepted_proposal_dict is not None
        else proposal
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


@register_negotiation_middleware("credit_quota_guard")
def credit_quota_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto when the quota snapshot can't cover the requested quantity."""
    offer = coerce_resource_dict(context.listing.get("offer_resource"))
    if offer.get("kind") != "api_credits.v1":
        return None, context

    quantity = context.intermediate.get("requested_quantity")
    if quantity is None:
        return None, context  # round-0 guard already rejected fresh threads
    quantity = int(quantity)

    resource_id = offer.get("resource_id")
    rows = (context.available_resources or {}).get("resources") or []
    for row in rows:
        if resource_id and str(row.get("resource_id")) != str(resource_id):
            continue
        available = row.get("available_units")
        if available is None:
            continue
        if int(available) >= quantity:
            return None, context
    return (
        NegotiationDecision(
            action="reject",
            reason=(
                f"{QUOTA_EXHAUSTED}: requested {quantity} token(s), "
                f"quota resource {resource_id!r} cannot cover it"
            ),
        ),
        context,
    )


@register_negotiation_middleware("key_owned_by_buyer_principal")
def key_owned_by_buyer_principal(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Reject an existing-key claim unless its canonical owner is the buyer."""
    if (context.intermediate.get("key_mode") or "new") != "existing":
        return None, context

    key_id = context.intermediate.get("key_id")
    record = context.intermediate.get("key_record")
    if not isinstance(record, dict):
        return (
            NegotiationDecision(
                action="reject",
                reason=f"{KEY_NOT_FOUND}: key {key_id!r} is not known to this seller",
            ),
            context,
        )
    if (record.get("status") or "active") != "active":
        return (
            NegotiationDecision(
                action="reject",
                reason=f"{KEY_REVOKED}: key {key_id!r} is {record.get('status')!r}",
            ),
            context,
        )

    owner_scheme = record.get("owner_scheme")
    owner_identifier = record.get("owner_id")
    if owner_scheme is None and owner_identifier is None:
        return None, context
    try:
        owner = Identity(
            scheme=IdentityScheme(str(owner_scheme)),
            identifier=str(owner_identifier),
        )
        buyer = Identity.model_validate(context.intermediate.get("buyer_principal"))
    except (TypeError, ValueError):
        return (
            NegotiationDecision(
                action="reject",
                reason=f"{KEY_NOT_OWNED}: key {key_id!r} has no matching principal",
            ),
            context,
        )
    if owner == buyer:
        return None, context
    return (
        NegotiationDecision(
            action="reject",
            reason=(
                f"{KEY_NOT_OWNED}: key {key_id!r} is bound to a different "
                "marketplace principal"
            ),
        ),
        context,
    )


__all__ = [
    "KEY_NOT_FOUND",
    "KEY_NOT_OWNED",
    "KEY_REVOKED",
    "QUOTA_EXHAUSTED",
    "api_credits_round_zero_guard",
    "key_owned_by_buyer_principal",
    "credit_quota_guard",
]
