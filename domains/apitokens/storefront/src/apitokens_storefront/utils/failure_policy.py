"""Fulfillment-failure policy for the API-tokens storefront.

Same configured-action-list shape as the VM storefront
(``[fulfillment.failure_policy].actions``), with the token domain's
repair set: ``release_capacity`` releases the deal's quota hold at the
ledger and reopens exhausted listings; ``emit_event`` and ``webhook``
behave identically to the VM versions. Issuance rollback (clawback +
revoke of a deal-created key) is inline in the fulfillment flow —
it must run exactly when issuance landed but the deal failed, which
the orchestrator knows and a generic action list doesn't.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from core_storefront.stage_log import stage_event

from .config import settings

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_ACTIONS = ("release_capacity", "emit_event")


@dataclass(frozen=True)
class FulfillmentFailureContext:
    allocation_id: str | None = None
    escrow_uid: str | None = None
    listing_id: str | None = None
    resource_id: str | None = None
    reason: str | None = None
    message: str | None = None
    source: str = "storefront"


@dataclass
class FulfillmentFailurePolicyResult:
    allocation_id: str | None = None
    state: str | None = None
    resource_id: str | None = None
    reopened_listing_ids: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)


def _coerce_actions(raw: Any) -> list[str]:
    if raw is None:
        return list(DEFAULT_FAILURE_ACTIONS)
    if isinstance(raw, str):
        actions = [raw]
    else:
        try:
            actions = list(raw)
        except TypeError:
            actions = []
    return [str(action).strip() for action in actions if str(action).strip()]


def configured_failure_actions() -> list[str]:
    return _coerce_actions(settings.get("fulfillment.failure_policy.actions"))


def _failure_payload(
    ctx: FulfillmentFailureContext,
    result: FulfillmentFailurePolicyResult,
) -> dict[str, Any]:
    return {
        "allocation_id": ctx.allocation_id,
        "escrow_uid": ctx.escrow_uid,
        "listing_id": ctx.listing_id,
        "resource_id": result.resource_id or ctx.resource_id,
        "reason": ctx.reason,
        "message": ctx.message,
        "source": ctx.source,
        "state": result.state,
        "reopened_listing_ids": result.reopened_listing_ids,
    }


async def _release_capacity(
    db: Any,
    ctx: FulfillmentFailureContext,
    capacity: Any | None = None,
) -> FulfillmentFailurePolicyResult:
    """Return the failed deal's quota through the ledger, reopen listings."""
    from apitokens_storefront.services.capacity_client import (
        build_capacity_client,
    )
    from apitokens_storefront.services.publication_service import (
        reopen_token_listings_after_capacity_change,
    )

    result = FulfillmentFailurePolicyResult(allocation_id=ctx.allocation_id)
    if capacity is None:
        capacity = build_capacity_client(lambda: db)

    allocation = await capacity.release(
        allocation_id=ctx.allocation_id,
        deal_ref={"escrow_uid": ctx.escrow_uid} if ctx.escrow_uid else None,
        failure_reason=ctx.reason,
        failure_message=ctx.message,
    )
    if allocation is not None:
        result.allocation_id = allocation.get("allocation_id")
        result.state = "released"
        result.resource_id = allocation.get("resource_id")
        result.reopened_listing_ids = (
            await reopen_token_listings_after_capacity_change(db, capacity)
        )
    return result


async def _send_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    url = str(settings.get("fulfillment.failure_policy.webhook_url", "") or "").strip()
    if not url:
        return {"action": "webhook", "status": "skipped", "reason": "webhook_url_empty"}
    try:
        timeout = float(
            settings.get("fulfillment.failure_policy.webhook_timeout", 5.0) or 5.0
        )
    except (TypeError, ValueError):
        timeout = 5.0
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
        if response.status_code >= 400:
            return {
                "action": "webhook",
                "status": "failed",
                "status_code": response.status_code,
                "body": response.text[:500],
            }
        return {
            "action": "webhook",
            "status": "sent",
            "status_code": response.status_code,
        }
    except Exception as exc:
        logger.warning("[FULFILLMENT_POLICY] failure webhook failed: %s", exc)
        return {"action": "webhook", "status": "failed", "error": str(exc)}


async def apply_fulfillment_failure_policy(
    db: Any,
    ctx: FulfillmentFailureContext,
    *,
    capacity: Any | None = None,
) -> FulfillmentFailurePolicyResult:
    actions = configured_failure_actions()
    result = FulfillmentFailurePolicyResult(allocation_id=ctx.allocation_id)

    for action in actions:
        if action == "release_capacity":
            try:
                released = await _release_capacity(db, ctx, capacity)
                result.allocation_id = released.allocation_id
                result.state = released.state
                result.resource_id = released.resource_id
                result.reopened_listing_ids = released.reopened_listing_ids
                result.actions.append({"action": action, "status": "ok"})
            except Exception as exc:
                logger.warning(
                    "[FULFILLMENT_POLICY] release_capacity failed: %s", exc,
                )
                result.actions.append(
                    {"action": action, "status": "failed", "error": str(exc)},
                )
        elif action == "emit_event":
            stage_event("fulfillment", "failed", **_failure_payload(ctx, result))
            result.actions.append({"action": action, "status": "ok"})
        elif action == "webhook":
            result.actions.append(await _send_webhook(_failure_payload(ctx, result)))
        else:
            result.actions.append(
                {"action": action, "status": "skipped", "reason": "unknown_action"},
            )

    return result
