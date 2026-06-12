"""API-tokens negotiation middlewares.

The scalar/escrow vocabulary (bisection, listed_price, escrow shape
guards, escrow-kind dispatch, the buyer counter guard) is shared with
the VM domain and lives in ``market_policy.scalar_policies``.
Importing that module also registers them, so an apitokens chain can
name them directly.

This module owns what is genuinely API-tokens vocabulary:

* ``api_tokens_round_zero_guard`` — validates and canonicalizes the
  opening round (quantity ≥ 1, proposal normalized against the
  listing's acceptance set, scalar amount present).
* ``token_quota_guard`` — the inventory-guard analog: requested
  quantity ≤ the quota resource's available units in the captured
  capacity snapshot. Advisory, like every negotiation-time check —
  issuance re-reserves authoritatively.
* ``key_owned_by_buyer_wallet`` — the seller-default ownership guard
  (design-api-tokens-domain.md, "Key ownership"): for an existing-key
  claim, the captured key record's ``wallet`` owner must equal the
  negotiation's signing wallet. Free — the wallet-signed negotiation is
  the possession proof. The guard is the interface, not the
  enforcement: issuance re-checks the claim at grant time.
"""

from __future__ import annotations

import logging

from domains.apitokens.listings.models import coerce_resource_dict
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

# Reject vocabulary shared with the tokens service (the service's
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


@register_negotiation_middleware("api_tokens_round_zero_guard")
def api_tokens_round_zero_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Validate and canonicalize the API-tokens opening round."""
    if not _is_round_zero(history):
        return None, context

    listing = context.listing or {}
    quantity = context.intermediate.get("requested_quantity")
    if quantity is None:
        return (
            NegotiationDecision(
                action="reject",
                reason="token_quantity_missing: provision_terms.payload.quantity is required",
            ),
            context,
        )
    if int(quantity) < 1:
        return (
            NegotiationDecision(
                action="reject",
                reason="token_quantity_invalid: quantity must be >= 1",
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
    accepted = _loads_json_list(listing.get("accepted_escrows"))
    accepted_proposal_dict = None
    if isinstance(proposal, dict):
        try:
            from market_alkahest.schemas import (
                EscrowProposal,
                normalize_proposal_against_accepted_escrows,
            )

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


@register_negotiation_middleware("token_quota_guard")
def token_quota_guard(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Veto when the quota snapshot can't cover the requested quantity."""
    offer = coerce_resource_dict(context.listing.get("offer_resource"))
    if offer.get("kind") != "api_tokens.v1":
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


@register_negotiation_middleware("key_owned_by_buyer_wallet")
def key_owned_by_buyer_wallet(
    history: list[NegotiationRound],
    context: NegotiationContext,
) -> NegotiationStep:
    """Reject an existing-key claim unless the buyer's wallet owns the key.

    Consults the captured key record (the tokens-service lookup the
    round hook snapshots, exactly like the inventory snapshot) and the
    negotiation's signing wallet. New-key deals pass untouched. A seller
    who wants open top-up omits this guard from their chain.
    """
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
    if owner_scheme is None:
        return None, context  # unowned key: anyone may top it up

    buyer_wallet = str(context.intermediate.get("buyer_wallet") or "")
    if owner_scheme == "wallet":
        owner_id = str(record.get("owner_id") or "")
        if buyer_wallet and owner_id and buyer_wallet.lower() == owner_id.lower():
            return None, context
        return (
            NegotiationDecision(
                action="reject",
                reason=(
                    f"{KEY_NOT_OWNED}: key {key_id!r} is bound to a different wallet"
                ),
            ),
            context,
        )

    # Non-wallet ownership (e.g. ed25519) needs the possession-challenge
    # middleware, which is the planned second scheme — this guard cannot
    # verify it and must not silently credit.
    return (
        NegotiationDecision(
            action="reject",
            reason=(
                f"{KEY_NOT_OWNED}: key {key_id!r} ownership scheme "
                f"{owner_scheme!r} is not verifiable by the wallet guard"
            ),
        ),
        context,
    )


__all__ = [
    "KEY_NOT_FOUND",
    "KEY_NOT_OWNED",
    "KEY_REVOKED",
    "QUOTA_EXHAUSTED",
    "api_tokens_round_zero_guard",
    "key_owned_by_buyer_wallet",
    "token_quota_guard",
]
