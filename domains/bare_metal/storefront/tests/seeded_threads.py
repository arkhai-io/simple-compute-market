"""Negotiation threads seeded as the negotiation runtime records them.

For tests whose subject comes after negotiation (settlement, persistence): the
same repository writes the runtime makes for an opening and, when accepted, for
its acceptance, without running a policy or a source check.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from arkhai_bare_metal import BareMetalMessage, BareMetalTerms
from market_identity import Identity


async def seed_thread(
    db: Any,
    *,
    negotiation_id: str,
    listing_id: str,
    buyer_principal: Identity,
    seller_principal: Identity,
    message: BareMetalMessage,
    proposal: dict[str, Any],
    amount: int,
    terms: BareMetalTerms | None = None,
) -> None:
    """Record an opening; with ``terms``, record it accepted at ``amount``."""

    now = datetime.now(timezone.utc).isoformat()
    await db.create_negotiation_thread(
        negotiation_id=negotiation_id,
        our_listing_id=listing_id,
        their_listing_id="",
        our_agent_id="http://seller:8000",
        their_agent_id="https://buyer.example",
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
        owner_id="http://seller:8000",
        our_initial_price=amount,
        our_strategy="listed",
        requested_duration_seconds=message.duration_seconds,
        buyer_escrow_proposal=proposal,
        provision_terms=message.model_dump(mode="json", exclude_none=True),
    )
    await db.save_negotiation_message(
        negotiation_id=negotiation_id,
        sender_principal=buyer_principal,
        sender_role="buyer",
        our_price=amount,
        their_price=amount,
        proposed_price=amount,
        action_taken="make_offer",
        message_type="initial_proposal",
        timestamp=now,
    )
    await db.copy_listing_binding_to_thread(
        negotiation_id=negotiation_id, listing_id=listing_id
    )
    await db.save_bare_metal_message(negotiation_id=negotiation_id, message=message)
    if terms is None:
        return
    await db.save_negotiation_message(
        negotiation_id=negotiation_id,
        sender_principal=seller_principal,
        sender_role="seller",
        our_price=amount,
        their_price=amount,
        proposed_price=amount,
        action_taken="accept_offer",
        message_type="accepted",
        timestamp=now,
    )
    await db.commit_agreed_terms(
        negotiation_id=negotiation_id,
        agreed_price=amount,
        agreed_duration_seconds=message.duration_seconds,
    )
    await db.save_bare_metal_terms(negotiation_id=negotiation_id, terms=terms)
    await db.update_negotiation_thread_terminal(
        negotiation_id=negotiation_id, terminal_state="success"
    )
