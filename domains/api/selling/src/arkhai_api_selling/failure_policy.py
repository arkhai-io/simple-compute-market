"""The ordered failure actions a storefront applies when its own issuance fails."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from market_settlement_runtime import FailurePolicy

from arkhai_api_selling.issuance import accepted_agreement
from arkhai_api_selling.quota_listing import listing_binding

DEFAULT_FAILURE_ACTIONS = ("release_capacity", "emit_event")

CapacityRuntimeFactory = Callable[[Any], Any]
"""Builds the storefront's capacity runtime over a repository."""

ReopenListings = Callable[[Any, Any], Awaitable[list[str]]]
"""Reopens the listings capacity released for, given a repository and an availability view."""


def build_failure_policy(
    *,
    actions_provider: Callable[[], Any],
    capacity_runtime: CapacityRuntimeFactory,
    reopen_listings: ReopenListings,
    webhook_target: Callable[[], tuple[str, float]],
    stages: Mapping[str, Any],
    composition: Callable[[], Any],
    stage_event: Callable[..., Any],
) -> FailurePolicy:
    """Compose the runtime's ordered dispatch with the family's failure actions.

    ``composition`` returns the storefront's settlement composition once it is built.
    """

    async def release_capacity(db: Any, context: dict[str, Any]) -> dict[str, Any]:
        binding = await listing_binding(db, str(context.get("listing_id") or ""))
        if binding is None:
            raise RuntimeError("capacity recovery requires a durable listing binding")
        capacity = capacity_runtime(db)
        reservation = await capacity.release(
            binding,
            capacity_reservation_id=context.get("capacity_reservation_id"),
            deal_ref=(
                {"negotiation_id": context["negotiation_id"]}
                if context.get("negotiation_id")
                else None
            ),
            failure_reason=context.get("reason"),
            failure_message=context.get("message"),
        )
        reopened_listing_ids: list[str] = []
        if reservation is not None:
            context["capacity_reservation_id"] = reservation.get("capacity_reservation_id")
            context["state"] = "released"
            context["resource_id"] = reservation.get("resource_id")
            reopened_listing_ids = await reopen_listings(db, await capacity.availability())
            context["reopened_listing_ids"] = reopened_listing_ids
        return {
            "status": "succeeded",
            "state": context.get("state"),
            "resource_id": context.get("resource_id"),
            "reopened_listing_ids": reopened_listing_ids,
        }

    async def emit_event(_db: Any, context: dict[str, Any]) -> dict[str, Any]:
        stage_event("fulfillment", "failed", **context)
        return {"status": "succeeded"}

    async def webhook(_db: Any, context: dict[str, Any]) -> dict[str, Any]:
        url, timeout = webhook_target()
        if not url:
            return {"status": "skipped", "reason": "webhook_url_empty"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=context)
        if response.status_code >= 400:
            return {
                "status": "failed",
                "status_code": response.status_code,
                "body": response.text[:500],
            }
        return {"status": "sent", "status_code": response.status_code}

    async def refund(db: Any, context: dict[str, Any]) -> dict[str, Any]:
        """Refund the buyer when this storefront's own issuance failed; opt-in.

        The accepted Agreement's seller stage decides: a stage with seller
        refunds reverses only when nothing was issued, and any other stage
        records why it skipped.
        """
        negotiation_id = str(context.get("negotiation_id") or context.get("escrow_uid") or "")
        thread = (
            await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            if negotiation_id
            else None
        )
        try:
            agreement, _raw = accepted_agreement(thread or {})
        except (KeyError, TypeError, ValueError):
            return {"action": "refund", "status": "skipped", "reason": "accepted_agreement_unavailable"}
        stage = stages.get(agreement.settlement.mechanism)
        if stage is None:
            return {"action": "refund", "status": "skipped", "reason": "refund_not_supported"}
        return await stage.refund_before_delivery(
            db=db,
            composition=composition(),
            negotiation_id=negotiation_id,
        )

    return FailurePolicy(
        actions_provider=actions_provider,
        handlers={
            "release_capacity": release_capacity,
            "emit_event": emit_event,
            "webhook": webhook,
            "refund": refund,
        },
    )
