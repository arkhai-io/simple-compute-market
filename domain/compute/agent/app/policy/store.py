"""Live policy callables for the compute domain.

Pre-thread negotiate-request guards (`negotiate.guard.*`) — these run from
`policy_service.consult_pre_negotiation_guards` against every incoming
`POST /negotiate/new`. The composite chains guards; the first to return
`REJECT_OFFER` short-circuits the negotiation with HTTP 409.

Negotiation round decisions go through `sync_negotiation.py` directly
via `NegotiationStrategy`, not the `@policy_callable` chain.
"""

from __future__ import annotations

import logging
from typing import Any

from market_storefront.models.domain_models import (
    Action as DomainAction,
    ActionType as DomainActionType,
    DecisionContext,
    NegotiationRequestedEvent,
)
from market_policy.registry import policy_callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pre-thread negotiation guards (used inside the negotiate_request composite)
# ---------------------------------------------------------------------------


def _coerce_resource_dict(value: Any) -> dict[str, Any]:
    """Listings persist offer/demand as JSON text; normalise to a dict."""
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


@policy_callable("negotiate.guard.has_matching_inventory")
def negotiate_guard_has_matching_inventory(
    context: DecisionContext,
) -> DomainAction | None:
    """Veto a negotiation request when no available portfolio resource
    matches the listing's offer (gpu_model + region).

    Designed for the *immediate-deal* seller: capacity must exist now.
    Operators running futures or off-chain-matched flows drop this guard
    from the negotiate-request composite — the seller will then accept
    threads against listings whose inventory will materialise later.

    Read-only against ``context.available_resources["resources"]``
    (which ``policy_service._consult_policy`` populates from
    ``db.list_resources()``); never mutates state. Listings whose offer
    isn't compute (token-for-token swaps) are treated as always-
    fulfillable here — capacity for those is enforced by the chain.
    """
    if not isinstance(context.event, NegotiationRequestedEvent):
        return None

    offer = _coerce_resource_dict(context.event.listing.get("offer_resource"))
    if "gpu_model" not in offer:
        return None  # not a compute listing — pass through

    required: dict[str, Any] = {}
    for key in ("region", "gpu_model"):
        v = offer.get(key)
        if v is not None:
            required[key] = v

    portfolio_raw = (context.available_resources or {}).get("resources") or []
    for row in portfolio_raw:
        # ``available_resources`` carries the full SQLite row — only
        # ``state == 'available'`` rows are eligible. The portfolio loader
        # in ``policy_service`` returns every resource regardless of
        # state, so we filter here.
        if (row.get("state") or "").strip() != "available":
            continue
        attrs = row.get("attributes")
        if isinstance(attrs, str):
            try:
                import json
                attrs = json.loads(attrs)
            except (ValueError, TypeError):
                continue
        if not isinstance(attrs, dict):
            continue
        if all(attrs.get(k) == v for k, v in required.items()):
            return None  # found a match, pass

    return DomainAction(
        action_type=DomainActionType.REJECT_OFFER,
        parameters={
            "reason": "no_matching_inventory",
            "listing_id": context.event.listing_id,
        },
    )


_ZERO_ADDRESS = "0x" + "0" * 40


def _normalize_escrow_field(value: Any) -> Any:
    """Case-insensitive compare for hex addresses; identity otherwise."""
    if isinstance(value, str) and value.startswith("0x") and len(value) == 42:
        return value.lower()
    return value


@policy_callable("negotiate.guard.escrow_fields_strict_match")
def negotiate_guard_escrow_fields_strict_match(
    context: DecisionContext,
) -> DomainAction | None:
    """Veto a negotiation request when the buyer's escrow proposal
    diverges from the seller's advertised ``accepted_escrows`` entry on
    any field the seller pinned.

    Strict equality: every key the seller set on the matched entry's
    ``fields`` map must equal the buyer's value. Operators who want
    softer matching (allow the buyer to upgrade arbiter, swap payment
    token, etc.) drop this guard from the composite and write their own.

    Passes through when:
      * no escrow_proposal in the event (legacy buyer client),
      * listing has no ``accepted_escrows`` advertised (publish-time
        synthesis couldn't resolve a chain — the seller is on their own),
      * proposal's ``escrow_address`` is the zero placeholder (legacy
        clients that don't pick an entry).

    The structural ``(chain, address)`` lookup against
    ``accepted_escrows`` lives in ``sync_negotiation._match_accepted_escrow``
    — that's protocol-fixed shape resolution. Here we only express the
    *seller's* opinion about which fields must match.
    """
    if not isinstance(context.event, NegotiationRequestedEvent):
        return None
    proposal = context.event.escrow_proposal
    if not isinstance(proposal, dict):
        return None

    listing = context.event.listing or {}
    accepted = listing.get("accepted_escrows")
    if isinstance(accepted, str):
        import json
        try:
            accepted = json.loads(accepted)
        except (ValueError, TypeError):
            return None
    if not isinstance(accepted, list) or not accepted:
        return None

    proposal_addr_raw = proposal.get("escrow_address")
    if not isinstance(proposal_addr_raw, str) or not proposal_addr_raw:
        return None
    proposal_addr = proposal_addr_raw.lower()
    if proposal_addr == _ZERO_ADDRESS:
        return None

    proposal_chain = proposal.get("chain_name")
    proposal_fields = proposal.get("fields") or {}

    matched: dict[str, Any] | None = None
    for entry in accepted:
        if not isinstance(entry, dict):
            continue
        entry_addr = entry.get("escrow_address")
        if (
            entry.get("chain_name") == proposal_chain
            and isinstance(entry_addr, str)
            and entry_addr.lower() == proposal_addr
        ):
            matched = entry
            break
    if matched is None:
        # No structural match in this composite — the protocol layer in
        # sync_negotiation handles the "address advertised but not in
        # set" rejection. Don't double-report from here.
        return None

    seller_fields = matched.get("fields") or {}
    if not isinstance(seller_fields, dict):
        return None

    for key, seller_value in seller_fields.items():
        buyer_value = proposal_fields.get(key) if isinstance(proposal_fields, dict) else None
        if _normalize_escrow_field(buyer_value) != _normalize_escrow_field(seller_value):
            return DomainAction(
                action_type=DomainActionType.REJECT_OFFER,
                parameters={
                    "reason": (
                        f"escrow_field_mismatch: field {key!r} — buyer "
                        f"proposed {buyer_value!r}, listing requires "
                        f"{seller_value!r}"
                    ),
                    "listing_id": context.event.listing_id,
                    "field": key,
                },
            )
    return None


