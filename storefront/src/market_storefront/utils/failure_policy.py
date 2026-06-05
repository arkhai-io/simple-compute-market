from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from market_storefront.services.compute_listing_reconciler import (
    closed_available_listing_ids,
    mark_derived_listings_open,
)
from market_storefront.utils.config import settings
from market_storefront.utils.stage_log import stage_event

logger = logging.getLogger(__name__)


DEFAULT_FAILURE_ACTIONS = ("release_capacity", "emit_event")


@dataclass(frozen=True)
class FulfillmentFailureContext:
    allocation_id: str | None = None
    escrow_uid: str | None = None
    listing_id: str | None = None
    provider_id: str | None = None
    provider_job_id: str | None = None
    provider_resource_id: str | None = None
    resource_id: str | None = None
    reason: str | None = None
    message: str | None = None
    logs_ref: str | None = None
    source: str = "storefront"


@dataclass
class FulfillmentFailurePolicyResult:
    allocation_id: str | None = None
    state: str | None = None
    resource_id: str | None = None
    gpu_count: int | None = None
    resource_state: str | None = None
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
    cfg = getattr(settings, "fulfillment", None)
    policy = getattr(cfg, "failure_policy", None) if cfg is not None else None
    return _coerce_actions(getattr(policy, "actions", None) if policy is not None else None)


def _webhook_url() -> str:
    cfg = getattr(settings, "fulfillment", None)
    policy = getattr(cfg, "failure_policy", None) if cfg is not None else None
    return str(getattr(policy, "webhook_url", "") or "").strip()


def _webhook_timeout() -> float:
    cfg = getattr(settings, "fulfillment", None)
    policy = getattr(cfg, "failure_policy", None) if cfg is not None else None
    try:
        return float(getattr(policy, "webhook_timeout", 5.0) or 5.0)
    except (TypeError, ValueError):
        return 5.0


def _failure_payload(
    ctx: FulfillmentFailureContext,
    result: FulfillmentFailurePolicyResult,
) -> dict[str, Any]:
    return {
        "allocation_id": ctx.allocation_id,
        "escrow_uid": ctx.escrow_uid,
        "listing_id": ctx.listing_id,
        "provider_id": ctx.provider_id,
        "provider_job_id": ctx.provider_job_id,
        "provider_resource_id": ctx.provider_resource_id,
        "resource_id": result.resource_id or ctx.resource_id,
        "reason": ctx.reason,
        "message": ctx.message,
        "logs_ref": ctx.logs_ref,
        "source": ctx.source,
        "state": result.state,
        "resource_state": result.resource_state,
        "reopened_listing_ids": result.reopened_listing_ids,
    }


async def _resolve_listing_id(db: Any, ctx: FulfillmentFailureContext) -> str | None:
    if ctx.listing_id:
        return ctx.listing_id
    if ctx.escrow_uid and hasattr(db, "get_listing_id_by_escrow_uid"):
        return await db.get_listing_id_by_escrow_uid(escrow_uid=ctx.escrow_uid)
    return None


async def _load_thread_for_escrow(db: Any, escrow_uid: str | None) -> dict[str, Any] | None:
    if not escrow_uid or not hasattr(db, "load_escrow"):
        return None
    escrow = await db.load_escrow(escrow_uid=escrow_uid)
    negotiation_id = (escrow or {}).get("negotiation_id")
    if not negotiation_id or not hasattr(db, "load_negotiation_thread_row"):
        return None
    return await db.load_negotiation_thread_row(negotiation_id=negotiation_id)


def _thread_duration_seconds(thread: dict[str, Any]) -> int:
    for key in ("agreed_duration_seconds", "requested_duration_seconds"):
        raw = thread.get(key)
        if raw is None:
            continue
        try:
            duration = int(raw)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            return duration
    return 3600


async def _refund_from_escrow_proposal(
    db: Any,
    *,
    ctx: FulfillmentFailureContext,
    listing_id: str,
    buyer: str,
    thread: dict[str, Any],
) -> dict[str, Any] | None:
    proposal_raw = thread.get("buyer_escrow_proposal")
    if not isinstance(proposal_raw, dict):
        return None
    if not ctx.escrow_uid or not hasattr(db, "load_escrow"):
        return {"action": "refund", "status": "skipped", "reason": "escrow_uid_unknown"}

    escrow = await db.load_escrow(escrow_uid=ctx.escrow_uid)
    chain_name = (escrow or {}).get("chain_name") or proposal_raw.get("chain_name")
    escrow_address = (escrow or {}).get("escrow_address") or proposal_raw.get("escrow_address")
    if not chain_name or not escrow_address:
        return {"action": "refund", "status": "failed", "reason": "escrow_chain_unknown"}

    from market_storefront.utils.config import CHAINS
    from service.clients.alkahest import (
        get_escrow_codec_for,
        materialize_escrow_terms_from_proposal,
    )
    from service.schemas import EscrowProposal

    chain_cfg = CHAINS.get(chain_name)
    if chain_cfg is None:
        return {
            "action": "refund",
            "status": "failed",
            "reason": "chain_not_configured",
            "chain_name": chain_name,
        }

    private_key = str(settings.wallet.private_key or "").strip()
    if not private_key:
        return {"action": "refund", "status": "skipped", "reason": "wallet_private_key_empty"}

    try:
        proposal = EscrowProposal.model_validate(proposal_raw)
        terms = materialize_escrow_terms_from_proposal(
            proposal=proposal,
            seller_wallet_address=settings.wallet.address or None,
            agreed_amount=(
                int(thread["agreed_price"])
                if thread.get("agreed_price") is not None
                else None
            ),
            duration_seconds=_thread_duration_seconds(thread),
            addr_config_path=chain_cfg.alkahest_address_config_path,
        )[0]
        codec = get_escrow_codec_for(
            chain_name,
            escrow_address,
            config_path=chain_cfg.alkahest_address_config_path,
        )
    except Exception as exc:
        return {
            "action": "refund",
            "status": "failed",
            "reason": "escrow_refund_context_invalid",
            "detail": str(exc),
        }

    try:
        result = await codec.refund_claimed(
            private_key=private_key,
            rpc_url=chain_cfg.rpc_url,
            obligation_data=terms.obligation_data,
            to_address=buyer,
        )
    except NotImplementedError as exc:
        return {
            "action": "refund",
            "status": "skipped",
            "reason": "refund_not_supported",
            "escrow_kind": codec.kind,
            "detail": str(exc),
        }
    except RuntimeError as exc:
        return {
            "action": "refund",
            "status": "failed",
            "reason": "token_transfer_failed",
            "escrow_kind": codec.kind,
            "detail": str(exc),
        }

    if hasattr(db, "update_listing"):
        await db.update_listing(listing_id=listing_id, status="refunded")
    if hasattr(db, "update_escrow") and ctx.escrow_uid:
        await db.update_escrow(escrow_uid=ctx.escrow_uid, status="refunded")
    stage_event(
        "post_settlement",
        "refund_transferred",
        listing_id=listing_id,
        escrow_uid=ctx.escrow_uid,
        escrow_kind=codec.kind,
        tx_hash=(
            result.get("tx_hash")
            or next(
                (
                    transfer.get("tx_hash")
                    for transfer in result.get("transfers", [])
                    if isinstance(transfer, dict)
                ),
                None,
            )
        ),
    )
    return {
        "action": "refund",
        "status": "refunded",
        "escrow_kind": codec.kind,
        "body": result,
    }


async def _release_capacity(
    db: Any,
    ctx: FulfillmentFailureContext,
) -> FulfillmentFailurePolicyResult:
    result = FulfillmentFailurePolicyResult(allocation_id=ctx.allocation_id)
    allocation = None
    if ctx.allocation_id and hasattr(db, "update_compute_allocation_state"):
        allocation = await db.update_compute_allocation_state(
            allocation_id=ctx.allocation_id,
            state="released",
            provider_id=ctx.provider_id,
            provider_job_id=ctx.provider_job_id,
            provider_resource_id=ctx.provider_resource_id,
            failure_reason=ctx.reason,
            failure_message=ctx.message,
            logs_ref=ctx.logs_ref,
        )
    elif ctx.escrow_uid and hasattr(db, "update_compute_allocation_state"):
        allocation = await db.update_compute_allocation_state(
            escrow_uid=ctx.escrow_uid,
            state="released",
            provider_id=ctx.provider_id,
            provider_job_id=ctx.provider_job_id,
            provider_resource_id=ctx.provider_resource_id,
            failure_reason=ctx.reason,
            failure_message=ctx.message,
            logs_ref=ctx.logs_ref,
        )

    if allocation is not None:
        result.allocation_id = allocation.get("allocation_id")
        result.state = "released"
        result.resource_id = allocation.get("resource_id")
        result.gpu_count = allocation.get("gpu_count")
        result.resource_state = allocation.get("resource_state")
    elif ctx.resource_id and hasattr(db, "apply_resource_set_transition"):
        row = await db.apply_resource_set_transition(
            resource_id=ctx.resource_id,
            event_type="reservation_released_after_fulfillment_failure",
            idempotency_key=f"failure-release:{ctx.escrow_uid or ctx.resource_id}",
            set_state="available",
        )
        result.resource_id = ctx.resource_id
        result.state = "released"
        result.resource_state = (row or {}).get("state")

    if result.state == "released":
        reopened = closed_available_listing_ids(db.db_path)
        for listing_id in reopened:
            await db.update_listing(listing_id=listing_id, status="open")
        mark_derived_listings_open(db.db_path, reopened)
        result.reopened_listing_ids = reopened
    return result


async def _send_webhook(
    payload: dict[str, Any],
) -> dict[str, Any]:
    url = _webhook_url()
    if not url:
        return {"action": "webhook", "status": "skipped", "reason": "webhook_url_empty"}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=_webhook_timeout()) as client:
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


async def _refund(
    db: Any,
    ctx: FulfillmentFailureContext,
    listing_id: str | None,
) -> dict[str, Any]:
    if not listing_id:
        return {"action": "refund", "status": "skipped", "reason": "listing_id_unknown"}

    thread = await _load_thread_for_escrow(db, ctx.escrow_uid)
    buyer = (thread or {}).get("buyer")
    if not buyer:
        return {"action": "refund", "status": "skipped", "reason": "buyer_unknown"}

    result = await _refund_from_escrow_proposal(
        db,
        ctx=ctx,
        listing_id=listing_id,
        buyer=buyer,
        thread=thread or {},
    )
    if result is None:
        return {"action": "refund", "status": "skipped", "reason": "proposal_unknown"}
    return result


async def apply_fulfillment_failure_policy(
    db: Any,
    ctx: FulfillmentFailureContext,
) -> FulfillmentFailurePolicyResult:
    actions = configured_failure_actions()
    listing_id = await _resolve_listing_id(db, ctx)
    ctx = FulfillmentFailureContext(**{**ctx.__dict__, "listing_id": listing_id})
    result = FulfillmentFailurePolicyResult(allocation_id=ctx.allocation_id)

    for action in actions:
        if action == "release_capacity":
            try:
                released = await _release_capacity(db, ctx)
                result.allocation_id = released.allocation_id
                result.state = released.state
                result.resource_id = released.resource_id
                result.gpu_count = released.gpu_count
                result.resource_state = released.resource_state
                result.reopened_listing_ids = released.reopened_listing_ids
                result.actions.append({"action": action, "status": "ok"})
            except Exception as exc:
                logger.warning("[FULFILLMENT_POLICY] release_capacity failed: %s", exc)
                result.actions.append({"action": action, "status": "failed", "error": str(exc)})
        elif action == "emit_event":
            payload = _failure_payload(ctx, result)
            stage_event("fulfillment", "failed", **payload)
            result.actions.append({"action": action, "status": "ok"})
        elif action == "webhook":
            result.actions.append(await _send_webhook(_failure_payload(ctx, result)))
        elif action == "refund":
            result.actions.append(await _refund(db, ctx, listing_id))
        else:
            result.actions.append({"action": action, "status": "skipped", "reason": "unknown_action"})

    return result
