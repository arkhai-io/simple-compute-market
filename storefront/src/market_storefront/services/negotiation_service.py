"""Negotiation service — business logic for the negotiations API.

The controller layer owns HTTP concerns (param extraction, response
serialisation, status codes).  This module owns the business rules:

- What does it mean to advance a negotiation?
- What preconditions must hold for force-accept?
- How is negotiation detail assembled from multiple tables?

All public methods accept a ``sqlite_client`` and return plain dicts or
raise ``NegotiationServiceError`` on business-rule violations.  The
controller converts those exceptions to the appropriate HTTP responses.

This separation keeps the business rules independently unit-testable
with a mock ``sqlite_client`` — no HTTP layer involved.
"""

from __future__ import annotations

import logging
from typing import Any

from market_storefront.utils.stage_log import stage_event
from market_storefront.utils.sync_negotiation import continue_sync_negotiation

logger = logging.getLogger(__name__)


class NegotiationServiceError(Exception):
    """Business-rule violation in the negotiation service.

    Carries an HTTP-friendly ``status_code`` so the controller can
    translate without embedding HTTP logic here.
    """

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class NegotiationService:
    """Stateless service — constructed per-request or shared; holds no mutable state."""

    def __init__(self, *, sqlite_client: Any) -> None:
        self._db = sqlite_client

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_for_order(
        self,
        *,
        listing_id: str,
        terminal_state: str | None = None,
        buyer_address: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return paginated negotiation threads for a seller order.

        Raises ``NegotiationServiceError(404)`` if the order is not found.
        """
        order = await self._db.load_listing(listing_id=listing_id)
        if not order:
            raise NegotiationServiceError(
                f"Order {listing_id!r} not found", status_code=404
            )
        return await self._db.list_negotiations_for_listing(
            listing_id=listing_id,
            terminal_state=terminal_state,
            buyer_address=buyer_address,
            limit=limit,
            offset=offset,
        )

    async def get_detail(
        self,
        *,
        listing_id: str,
        neg_id: str,
    ) -> dict[str, Any]:
        """Return full negotiation detail (thread + messages + stage events).

        Raises ``NegotiationServiceError(404)`` if not found or if the
        negotiation does not belong to the given order.
        """
        detail = await self._db.load_negotiation_detail(
            listing_id=listing_id, neg_id=neg_id
        )
        if not detail:
            raise NegotiationServiceError(
                f"Negotiation {neg_id!r} not found for order {listing_id!r}",
                status_code=404,
            )
        return detail

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def advance(
        self,
        *,
        listing_id: str,
        neg_id: str,
        action: str,
        price: int | None,
        reason: str | None,
    ) -> dict[str, Any]:
        """Drive one negotiation round as the admin (no buyer signature required).

        Delegates to ``continue_sync_negotiation`` using the thread's
        recorded counterparty as the nominal buyer address so message
        attribution stays consistent.

        Raises:
            NegotiationServiceError(400) — invalid action or missing price
            NegotiationServiceError(404) — thread not found / wrong order
            NegotiationServiceError(409) — thread already terminal
        """
        if action not in ("counter", "accept", "exit"):
            raise NegotiationServiceError(
                "action must be 'counter'|'accept'|'exit'", status_code=400
            )
        if action == "counter" and price is None:
            raise NegotiationServiceError(
                "'price' required as int for counter", status_code=400
            )

        thread = await self._load_and_validate_thread(
            listing_id=listing_id, neg_id=neg_id, require_non_terminal=True
        )

        try:
            result = await continue_sync_negotiation(
                sqlite_client=self._db,
                neg_id=neg_id,
                buyer_action=action,
                buyer_price=price,
                buyer_reason=reason,
                # Use thread's counterparty so message attribution is consistent.
                buyer_address=thread.get("their_agent_id") or "admin",
            )
        except ValueError as exc:
            raise NegotiationServiceError(str(exc), status_code=400) from exc
        except Exception as exc:
            logger.error("[NEGOTIATION SERVICE] advance failed: %s", exc, exc_info=True)
            raise NegotiationServiceError(
                f"advance failed: {exc}", status_code=500
            ) from exc

        return {"neg_id": neg_id, "listing_id": listing_id, **result}

    async def force_accept(
        self,
        *,
        listing_id: str,
        neg_id: str,
        price: int,
    ) -> dict[str, Any]:
        """Commit a negotiation as terminal-success at the given price.

        Bypasses the strategy entirely.  The caller (admin) is responsible
        for choosing a price that makes business sense.

        Raises:
            NegotiationServiceError(404) — thread not found / wrong order
            NegotiationServiceError(409) — thread already terminal
        """
        thread = await self._load_and_validate_thread(
            listing_id=listing_id, neg_id=neg_id, require_non_terminal=True
        )

        our_order = await self._db.load_listing(listing_id=listing_id)
        # Echo the buyer's recorded duration ask. The thread row was loaded
        # above and carries `requested_duration_seconds` from /negotiate/new.
        # Falls back to the listing's max_duration_seconds, then 3600s, only
        # for legacy threads that pre-date this slice.
        agreed_duration_seconds = (
            thread.get("requested_duration_seconds")
            or (our_order or {}).get("max_duration_seconds")
            or 3600
        )

        # Write the acceptance message and terminal state directly via sqlite_client,
        # bypassing NegotiationThreadTransaction which requires the thread-store
        # singleton (initialised with identity+URL only during storefront startup).
        # For an admin-initiated force-accept there is no identity context needed.
        from datetime import datetime as _dt
        await self._db.save_negotiation_message(
            negotiation_id=neg_id,
            sender="admin",
            our_price=price,
            their_price=price,
            proposed_price=price,
            action_taken="accept_offer",
            message_type="accepted",
            timestamp=_dt.now().isoformat(),
        )
        await self._db.update_negotiation_thread_terminal(
            negotiation_id=neg_id,
            terminal_state="success",
        )

        await self._db.commit_agreed_terms(
            negotiation_id=neg_id,
            agreed_price=price,
            agreed_duration_seconds=int(agreed_duration_seconds),
        )

        stage_event(
            "negotiation", "force_accepted",
            negotiation_id=neg_id,
            listing_id=listing_id,
            agreed_price=price,
            source="admin",
        )

        return {
            "neg_id": neg_id,
            "listing_id": listing_id,
            "action": "accept",
            "price": price,
            "source": "admin_force_accept",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_and_validate_thread(
        self,
        *,
        listing_id: str,
        neg_id: str,
        require_non_terminal: bool = False,
    ) -> dict[str, Any]:
        """Load a thread and validate it belongs to listing_id.

        Raises NegotiationServiceError on any validation failure.
        """
        thread = await self._db.load_negotiation_thread_row(negotiation_id=neg_id)
        if not thread:
            raise NegotiationServiceError(
                f"Negotiation {neg_id!r} not found", status_code=404
            )
        if thread.get("our_listing_id") != listing_id:
            raise NegotiationServiceError(
                f"Negotiation {neg_id!r} does not belong to order {listing_id!r}",
                status_code=404,
            )
        if require_non_terminal and thread.get("terminal_state"):
            raise NegotiationServiceError(
                f"Negotiation {neg_id!r} is already in terminal state "
                f"{thread['terminal_state']!r}",
                status_code=409,
            )
        return thread
