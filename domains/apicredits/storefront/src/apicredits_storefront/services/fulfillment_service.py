"""Credit fulfillment orchestration for settled escrows.

Binds the concept module's ``fulfill_api_credits_obligation`` to this
process's parts: settings, the capacity-hold lookup placed at
acceptance, and the configured failure policy.
"""

from __future__ import annotations

import logging
from typing import Any

from core_storefront.stage_log import stage_event
from domains.apicredits.settlement import fulfill_api_credits_obligation
from market_settlement_runtime import FailurePolicy
from market_identity import Identity

from apicredits_storefront.services.credits_service_client import (
    get_credits_service_client,
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
    from apicredits_storefront.services.capacity_client import build_capacity_client
    from apicredits_storefront.services.publication_service import (
        reopen_token_listings_after_capacity_change,
    )

    capacity = build_capacity_client(lambda: db)
    reservation = await capacity.release(
        capacity_reservation_id=context.get("capacity_reservation_id"),
        deal_ref=(
            {"escrow_uid": context["escrow_uid"]} if context.get("escrow_uid") else None
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
            capacity,
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
    escrow_uid: str,
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
            "escrow_uid": escrow_uid,
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
    *,
    client: Any | None,
    escrow_uid: str,
    order: dict[str, Any],
    quantity: int,
    key_mode: str = "new",
    key_id: str | None = None,
    buyer_principal: Identity,
    listing_id: str | None = None,
    negotiation_id: str | None = None,
) -> dict[str, Any]:
    """Issue credits for a settled escrow and fulfill the obligation.

    When the negotiation's acceptance placed a TTL quota hold (two-phase
    reserve), its capacity_reservation_id rides the issuance call — the tokens
    service commits that hold open-ended instead of racing a fresh
    reserve. Consume-once: the hold row's job is done either way.
    """

    from apicredits_storefront.domain_runtime import (
        get_market_domain_contract,
    )

    held_reservation: dict | None = None
    if negotiation_id:
        db = get_sqlite_client()
        hold = await db.load_capacity_hold(negotiation_id=negotiation_id)
        if hold:
            held_reservation = dict(hold.get("payload") or {})
            held_reservation.setdefault(
                "capacity_reservation_id", hold.get("capacity_reservation_id")
            )
            await db.delete_capacity_hold(negotiation_id=negotiation_id)

    listing = get_market_domain_contract().codecs.listing(order)
    return await fulfill_api_credits_obligation(
        client=client,
        escrow_uid=escrow_uid,
        offer_resource=listing.offer_resource.model_dump(mode="json"),
        quantity=quantity,
        key_mode=key_mode,
        key_id=key_id,
        buyer_principal=buyer_principal,
        listing_id=listing_id,
        credits_client=get_credits_service_client(),
        stage_event=stage_event,
        apply_failure_policy=_apply_fulfillment_failure_policy_adapter,
        held_reservation=held_reservation,
    )
