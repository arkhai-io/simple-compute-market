"""Credit fulfillment orchestration from verified settlement evidence.

Binds the concept module's ``fulfill_api_credits_obligation`` to this
process's parts: settings, the capacity-hold lookup placed at
acceptance, and the configured failure policy.
"""

from __future__ import annotations

import logging
from typing import Any

from core_storefront.stage_log import stage_event
from domains.apicredits.settlement import fulfill_api_credits_obligation
from domains.apicredits.settlement.fulfillment import credit_delivery
from market_core import SettlementEvidence
from market_settlement_runtime import FailurePolicy

from apicredits_storefront.services.credits_service_client import (
    get_credits_service_client,
)
from apicredits_storefront.services.capacity_client import (
    build_capacity_runtime,
    capacity_binding_from_offer,
)
from apicredits_storefront.services.publication_service import (
    reopen_token_listings_after_capacity_change,
)
from apicredits_storefront.utils.config import settings
from apicredits_storefront.utils.sqlite_client import get_sqlite_client

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_ACTIONS = ("release_capacity", "emit_event")


def _configured_failure_actions() -> Any:
    raw = settings.get("fulfillment.failure_policy.actions")
    return DEFAULT_FAILURE_ACTIONS if raw is None else raw


async def _release_capacity_handler(
    db: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    listing_id = str(context.get("listing_id") or "")
    row = await db.load_listing(listing_id=listing_id)
    if row is None:
        raise RuntimeError("capacity recovery requires a durable listing binding")
    binding = capacity_binding_from_offer(row.get("offer_resource") or {})
    capacity = build_capacity_runtime(lambda: db)
    reservation = await capacity.release(
        binding,
        capacity_reservation_id=context.get("capacity_reservation_id"),
        deal_ref=(
            {"negotiation_id": context["negotiation_id"]} if context.get("negotiation_id") else None
        ),
        failure_reason=context.get("reason"),
        failure_message=context.get("message"),
    )
    reopened_listing_ids: list[str] = []
    if reservation is not None:
        context["capacity_reservation_id"] = reservation.get("capacity_reservation_id")
        context["state"] = "released"
        context["resource_id"] = reservation.get("resource_id")
        reopened_listing_ids = await reopen_token_listings_after_capacity_change(
            db,
            await capacity.availability(),
        )
        context["reopened_listing_ids"] = reopened_listing_ids
    return {
        "status": "succeeded",
        "state": context.get("state"),
        "resource_id": context.get("resource_id"),
        "reopened_listing_ids": reopened_listing_ids,
    }


async def _emit_failure_event_handler(
    _db: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    stage_event("fulfillment", "failed", **context)
    return {"status": "succeeded"}


async def _failure_webhook_handler(
    _db: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    url = str(settings.get("fulfillment.failure_policy.webhook_url", "") or "").strip()
    if not url:
        return {"status": "skipped", "reason": "webhook_url_empty"}
    try:
        timeout = float(
            settings.get("fulfillment.failure_policy.webhook_timeout", 5.0) or 5.0
        )
    except (TypeError, ValueError):
        timeout = 5.0

    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=context)
    if response.status_code >= 400:
        return {
            "status": "failed",
            "status_code": response.status_code,
            "body": response.text[:500],
        }
    return {"status": "sent", "status_code": response.status_code}


def build_api_credit_failure_policy() -> FailurePolicy:
    """Compose shared ordered dispatch with API-credit-owned effects."""
    return FailurePolicy(
        actions_provider=_configured_failure_actions,
        handlers={
            "release_capacity": _release_capacity_handler,
            "emit_event": _emit_failure_event_handler,
            "webhook": _failure_webhook_handler,
        },
    )


async def _apply_fulfillment_failure_policy_adapter(
    *,
    capacity_reservation_id: str | None,
    settlement_ref: str | None,
    negotiation_id: str,
    listing_id: str | None,
    resource_id: str | None,
    reason: str,
    message: str,
    source: str,
) -> None:
    import apicredits_storefront.container as container

    policy = container.resolved_failure_policy
    if policy is None:
        raise RuntimeError("API-credit failure policy is not initialized")
    await policy.apply(
        get_sqlite_client(),
        {
            "capacity_reservation_id": capacity_reservation_id,
            "settlement_ref": settlement_ref,
            "negotiation_id": negotiation_id,
            "listing_id": listing_id,
            "resource_id": resource_id,
            "reason": reason,
            "message": message,
            "source": source,
            "state": None,
            "reopened_listing_ids": [],
        },
    )


async def fulfill_credit_obligation(
    *, evidence: SettlementEvidence, retry_uncertain: bool = False,
    db: Any | None = None, credits_client: Any | None = None,
) -> dict[str, Any]:
    """Issue from verified delivery inputs, independently of their source mechanism."""
    credit_delivery(evidence)
    db = db if db is not None else get_sqlite_client()
    hold = await db.load_capacity_hold(negotiation_id=evidence.negotiation_id)
    held_reservation = None
    if hold:
        held_reservation = dict(hold.get("payload") or {})
        held_reservation.setdefault("capacity_reservation_id", hold.get("capacity_reservation_id"))
    result = await fulfill_api_credits_obligation(
        evidence=evidence, retry_uncertain=retry_uncertain,
        credits_client=credits_client or get_credits_service_client(),
        stage_event=stage_event, apply_failure_policy=_apply_fulfillment_failure_policy_adapter,
        held_reservation=held_reservation,
    )
    if held_reservation is not None and result.get("status") != "pending":
        await db.delete_capacity_hold(negotiation_id=evidence.negotiation_id)
    return result
