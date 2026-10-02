"""Framework-free deal controls every storefront binds behind its own authentication.

The stage-event read, the negotiation-opening preview, and administrative
acceptance have the same paths, bodies, and responses in every storefront, so one
typed client drives all of them. Each storefront binds these services into its
own router; the preview and acceptance run through the negotiation runtime, so
they cannot record negotiation state any other way.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from core_storefront.models.listing_models import (
    EvaluateNegotiateRequest,
    EvaluateNegotiateResponse,
)
from core_storefront.models.negotiation_models import (
    ForceAcceptRequest,
    ForceAcceptResponse,
)
from core_storefront.models.system_models import StageEventResponse
from market_identity import Identity
from market_negotiation_runtime import NegotiationStateError

from .lifecycle_routes import LifecycleRouteError


class DealControlRouteError(LifecycleRouteError):
    """HTTP-shaped failure of a deal control, raised without a web framework."""


def opening_proposal(proposal: Any, settlement_selection: Any) -> Any:
    """The proposal an opening hands the runtime, carrying any exact selection."""

    if settlement_selection is None:
        return proposal
    selection_payload = settlement_selection.model_dump(mode="json")
    if proposal is None:
        return {"settlement_selection": selection_payload}
    payload = dict(proposal) if isinstance(proposal, dict) else proposal.model_dump(
        mode="json"
    )
    payload["settlement_selection"] = selection_payload
    return payload


class StageEventRouteService:
    """Read one storefront's stage-event log as a page or a server-sent stream."""

    def __init__(self, repository: Any, *, poll_seconds: float = 0.2) -> None:
        self._db = repository
        self._poll_seconds = poll_seconds

    @staticmethod
    def resume_point(since_id: int, last_event_id: str | None) -> int:
        """A stream client's ``Last-Event-ID`` header wins over ``since_id``."""

        if last_event_id:
            try:
                return int(last_event_id)
            except (TypeError, ValueError):
                pass
        return since_id

    async def page(
        self,
        *,
        since_id: int,
        limit: int,
        stage: str | None = None,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
    ) -> StageEventResponse:
        """One page and whether more follows.

        A reader that concludes something about the whole log from a filtered
        page needs to know whether it saw the whole log; ``count`` alone cannot
        tell a log that ended on the page boundary from one that continues.
        """

        rows, truncated = await self._db.list_stage_events_page(
            after_id=since_id,
            limit=limit,
            stage=stage,
            listing_id=listing_id,
            negotiation_id=negotiation_id,
        )
        return StageEventResponse(events=rows, count=len(rows), truncated=truncated)

    async def stream(
        self,
        *,
        since_id: int,
        stage: str | None = None,
        listing_id: str | None = None,
        negotiation_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Server-sent events from ``since_id`` onward, indefinitely."""

        cursor = since_id
        while True:
            rows = await self._db.list_stage_events(
                after_id=cursor,
                limit=50,
                stage=stage,
                listing_id=listing_id,
                negotiation_id=negotiation_id,
            )
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\ndata: {json.dumps(row, default=str)}\n\n"
            if not rows:
                await asyncio.sleep(self._poll_seconds)


class NegotiationControlRouteService:
    """Preview an opening and accept a negotiation administratively."""

    def __init__(
        self,
        *,
        runtime: Any,
        repository: Any,
        seller_principal: Callable[[], Identity],
    ) -> None:
        self._runtime = runtime
        self._db = repository
        self._seller_principal = seller_principal

    async def evaluate_negotiate(
        self, listing_id: str, body: EvaluateNegotiateRequest
    ) -> EvaluateNegotiateResponse:
        """What ``negotiate/new`` would decide for this opening, writing nothing."""

        preview = await self._runtime.preview_opening(
            repository=self._db,
            listing_id=listing_id,
            buyer_principal=body.buyer_principal,
            seller_principal=self._seller_principal(),
            proposal=opening_proposal(body.proposal, body.settlement_selection),
            terms=body.provision_terms,
        )
        if preview.refused:
            return EvaluateNegotiateResponse(
                listing_id=listing_id,
                decision="refused",
                decision_reason=preview.refusal,
                would_negotiate=False,
                refused=True,
            )
        return EvaluateNegotiateResponse(
            listing_id=listing_id,
            our_reference_amount=preview.our_amount,
            their_proposed_amount=preview.their_amount,
            strategy=preview.strategy,
            decision=preview.decision,
            decision_amount=preview.decision_amount,
            decision_proposal=(
                dict(preview.decision_proposal)
                if preview.decision_proposal is not None
                else None
            ),
            decision_reason=preview.decision_reason,
            would_negotiate=preview.decision != "exit",
        )

    async def force_accept(
        self,
        listing_id: str,
        negotiation_id: str,
        body: ForceAcceptRequest,
        *,
        actor_principal: Identity,
    ) -> ForceAcceptResponse:
        """Accept at the administrator's amount through the runtime's acceptance."""

        try:
            result = await self._runtime.accept_administratively(
                repository=self._db,
                listing_id=listing_id,
                negotiation_id=negotiation_id,
                amount=int(body.amount),
                actor_principal=actor_principal,
            )
        except NegotiationStateError as exc:
            message = str(exc)
            status = (
                404
                if message.startswith("Unknown negotiation")
                or "does not belong" in message
                else 409
            )
            raise DealControlRouteError(status, message) from exc
        return ForceAcceptResponse(
            action=result["action"],
            amount=result["amount"],
            source=result["source"],
        )


__all__ = [
    "DealControlRouteError",
    "NegotiationControlRouteService",
    "StageEventRouteService",
    "opening_proposal",
]
