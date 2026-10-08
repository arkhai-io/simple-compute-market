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
from typing import Any, Awaitable, Callable
from market_identity import Identity


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

    def __init__(
        self,
        *,
        sqlite_client: Any,
        continue_negotiation: Callable[..., Awaitable[dict[str, Any]]],
        stage_event: Callable[..., None],
    ) -> None:
        self._db = sqlite_client
        self._continue_negotiation = continue_negotiation
        self._stage_event = stage_event

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_for_order(
        self,
        *,
        listing_id: str,
        terminal_state: str | None = None,
        buyer_principal: Identity | None = None,
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
            buyer_principal=buyer_principal,
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
        proposal: dict[str, Any] | None,
        reason: str | None,
        actor_principal: Identity,
    ) -> dict[str, Any]:
        """Drive one negotiation round as an authenticated administrator.

        Raises ``NegotiationServiceError`` for invalid, missing, or terminal
        negotiations and invalid proposals.
        """
        if action not in ("counter", "accept", "exit"):
            raise NegotiationServiceError(
                "action must be 'counter'|'accept'|'exit'", status_code=400
            )
        if action == "counter" and proposal is None:
            raise NegotiationServiceError(
                "'proposal' required for counter", status_code=400
            )

        thread = await self._load_and_validate_thread(
            listing_id=listing_id, neg_id=neg_id, require_non_terminal=True
        )

        try:
            result = await self._continue_negotiation(
                repository=self._db,
                negotiation_id=neg_id,
                buyer_action=action,
                buyer_proposal=proposal,
                buyer_reason=reason,
                actor_principal=actor_principal,
                actor_role="admin",
                buyer_principal=thread["buyer_principal"],
                seller_principal=thread["seller_principal"],
            )
        except ValueError as exc:
            raise NegotiationServiceError(str(exc), status_code=400) from exc
        except Exception as exc:
            logger.error("[NEGOTIATION SERVICE] advance failed: %s", exc, exc_info=True)
            raise NegotiationServiceError(
                f"advance failed: {exc}", status_code=500
            ) from exc

        return {"neg_id": neg_id, "listing_id": listing_id, **result}

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
