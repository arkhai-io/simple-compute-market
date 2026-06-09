"""Generic synchronous-negotiation helpers for storefront runtimes."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from market_policy.negotiation_middleware import NegotiationDecision
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


async def record_seller_decision_message(
    *,
    negotiation_id: str,
    sender: str,
    our_amount: int,
    their_amount: int,
    decision: NegotiationDecision,
    decision_amount: int | None,
) -> None:
    """Persist a seller decision as a negotiation message.

    ``decision_amount`` is supplied by the schema/domain wrapper because the
    core does not know how to interpret proposal payloads.
    """
    from market_policy.negotiation_thread import NegotiationThreadTransaction

    action_taken_map = {
        "counter": "counter_offer",
        "accept": "accept_offer",
        "exit": "exit_negotiation",
        "reject": "exit_negotiation",
    }
    message_type_map = {
        "counter": "counter_proposal",
        "accept": "accepted",
        "exit": "exit",
        "reject": "exit",
    }
    stored_amount = decision_amount if decision_amount is not None else their_amount

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_SELLER_DECISION") as txn:
        await txn.add_message(
            negotiation_id=negotiation_id,
            sender=sender,
            our_price=our_amount,
            their_price=their_amount,
            proposed_price=stored_amount,
            action_taken=action_taken_map[decision.action],
            message_type=message_type_map[decision.action],
        )
        if decision.action == "accept":
            await txn.mark_terminal(negotiation_id, "success")
        elif decision.action in ("exit", "reject"):
            await txn.mark_terminal(negotiation_id, "failure")


async def record_buyer_accept_message(
    *,
    negotiation_id: str,
    sender: str,
    our_amount: int,
    accepted_amount: int,
) -> None:
    """Persist buyer acceptance of the seller's latest counter."""
    from market_policy.negotiation_thread import NegotiationThreadTransaction

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_ACCEPT") as txn:
        await txn.add_message(
            negotiation_id=negotiation_id,
            sender=sender,
            our_price=our_amount,
            their_price=accepted_amount,
            proposed_price=accepted_amount,
            action_taken="accept_offer",
            message_type="accepted",
        )
        await txn.mark_terminal(negotiation_id, "success")


async def record_buyer_exit_message(
    *,
    negotiation_id: str,
    sender: str,
    our_amount: int,
) -> None:
    """Persist buyer exit and mark the negotiation failed."""
    from market_policy.negotiation_thread import NegotiationThreadTransaction

    async with NegotiationThreadTransaction("SYNC_NEGOTIATE_EXIT") as txn:
        await txn.add_message(
            negotiation_id=negotiation_id,
            sender=sender,
            our_price=our_amount,
            their_price=None,
            proposed_price=None,
            action_taken="exit_negotiation",
            message_type="exit",
        )
        await txn.mark_terminal(negotiation_id, "failure")
