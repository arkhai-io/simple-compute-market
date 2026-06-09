"""Generic synchronous-negotiation helpers for storefront runtimes."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from market_policy.negotiation_middleware import NegotiationRound


class StorefrontPausedError(Exception):
    """Raised when a new negotiation is attempted while unavailable."""

    def __init__(self, reason: str = "paused") -> None:
        super().__init__(reason)
        self.reason = reason


class OfferUnfulfillableError(Exception):
    """Raised when the seller refuses an otherwise valid offer."""

    def __init__(self, reason: str, *, listing_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.listing_id = listing_id


LIVE_LISTING_STATUSES = frozenset({"open"})
"""Listing statuses that can accept new negotiations."""


def proposal_with_amount(
    pinned: dict[str, Any] | None,
    amount: int | float | None,
) -> dict[str, Any] | None:
    """Overlay ``amount`` onto a pinned EscrowProposal-shaped dict."""
    if pinned is None and amount is None:
        return None
    pinned_fields = (pinned or {}).get("fields") if isinstance(pinned, dict) else None
    merged_fields: dict[str, Any] = (
        dict(pinned_fields) if isinstance(pinned_fields, dict) else {}
    )
    if amount is not None:
        merged_fields["amount"] = int(amount)
    if pinned is None:
        return {"fields": merged_fields}
    return {**pinned, "fields": merged_fields}


def coerce_pinned_proposal(value: Any) -> dict[str, Any] | None:
    """Parse a stored pinned proposal value into a dict when possible."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def history_from_messages(
    messages: list[dict[str, Any]],
    our_sender: str,
    *,
    buyer_pinned_proposal: dict[str, Any] | None,
) -> list[NegotiationRound]:
    """Convert persisted thread messages into policy-consumable rounds."""
    out: list[NegotiationRound] = []
    for i, message in enumerate(messages):
        sender = "us" if message.get("sender") == our_sender else "them"
        action = _action_from_stored_message(message.get("action_taken", ""))
        amount = _stored_amount(message.get("proposed_price"))
        proposal = (
            proposal_with_amount(buyer_pinned_proposal, amount)
            if amount is not None or buyer_pinned_proposal is not None
            else None
        )
        out.append(NegotiationRound(
            round_number=i,
            sender=sender,
            action=action,
            proposal=proposal,
        ))
    return out


def _action_from_stored_message(action_taken: str) -> str:
    if action_taken == "make_offer":
        return "initial"
    if action_taken == "counter_offer":
        return "counter"
    if action_taken == "accept_offer":
        return "accept"
    if action_taken == "exit_negotiation":
        return "exit"
    return "counter"


def _stored_amount(value: Any) -> int | None:
    try:
        return int(Decimal(str(value))) if value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return None
