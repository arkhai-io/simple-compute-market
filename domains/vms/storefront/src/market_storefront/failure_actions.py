"""VM-owned effects injected into the shared ordered failure policy."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from core_storefront.stage_log import stage_event
from domains.vms.listings.reconciler import (
    closed_available_listing_ids,
    mark_derived_listings_open,
)
from market_settlement_runtime import FailurePolicy
from market_identity import Identity

from market_storefront.utils.config import (
    get_evm_wallet_address,
    get_evm_wallet_private_key,
    settings,
)

logger = logging.getLogger(__name__)


DEFAULT_FAILURE_ACTIONS = ("release_capacity", "emit_event")


@dataclass(frozen=True)
class FulfillmentFailureContext:
    capacity_reservation_id: str | None = None
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
    capacity_reservation_id: str | None = None
    state: str | None = None
    resource_id: str | None = None
    gpu_count: int | None = None
    resource_state: str | None = None
    reopened_listing_ids: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)


def _configured_failure_actions_source() -> Any:
    cfg = getattr(settings, "fulfillment", None)
    policy = getattr(cfg, "failure_policy", None) if cfg is not None else None
    raw = getattr(policy, "actions", None) if policy is not None else None
    return DEFAULT_FAILURE_ACTIONS if raw is None else raw


def configured_failure_actions() -> list[str]:
    return list(_VM_FAILURE_POLICY.configured_actions())


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
        "capacity_reservation_id": ctx.capacity_reservation_id,
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


async def _load_thread_for_escrow(
    db: Any, escrow_uid: str | None
) -> dict[str, Any] | None:
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
    buyer_evm_address: str,
    thread: dict[str, Any],
) -> dict[str, Any] | None:
    proposal_raw = thread.get("buyer_escrow_proposal")
    if not isinstance(proposal_raw, dict):
        return None
    if not ctx.escrow_uid or not hasattr(db, "load_escrow"):
        return {"action": "refund", "status": "skipped", "reason": "escrow_uid_unknown"}

    escrow = await db.load_escrow(escrow_uid=ctx.escrow_uid)
    chain_name = (escrow or {}).get("chain_name") or proposal_raw.get("chain_name")
    escrow_address = (escrow or {}).get("escrow_address") or proposal_raw.get(
        "escrow_address"
    )
    if not chain_name or not escrow_address:
        return {
            "action": "refund",
            "status": "failed",
            "reason": "escrow_chain_unknown",
        }

    from market_alkahest.alkahest import (
        get_escrow_codec_for,
        materialize_escrow_terms_from_proposal,
    )
    from market_core.schemas import EscrowProposal

    from market_storefront.utils.config import CHAINS

    chain_cfg = CHAINS.get(chain_name)
    if chain_cfg is None:
        return {
            "action": "refund",
            "status": "failed",
            "reason": "chain_not_configured",
            "chain_name": chain_name,
        }

    private_key = get_evm_wallet_private_key()
    if not private_key:
        return {
            "action": "refund",
            "status": "skipped",
            "reason": "wallet_private_key_empty",
        }

    try:
        proposal = EscrowProposal.model_validate(proposal_raw)
        terms = materialize_escrow_terms_from_proposal(
            proposal=proposal,
            seller_wallet_address=get_evm_wallet_address() or None,
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
            to_address=buyer_evm_address,
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
    capacity: Any | None = None,
) -> FulfillmentFailurePolicyResult:
    """Release failed capacity at the listing's exact recorded site."""
    from market_capacity_publication import capacity_availability, remote_site_clients
    from market_storefront.services.capacity_client import (
        build_capacity_runtime,
        capacity_binding_for_listing,
    )

    result = FulfillmentFailurePolicyResult(
        capacity_reservation_id=ctx.capacity_reservation_id
    )
    if not ctx.listing_id:
        raise RuntimeError("capacity release requires the persisted listing binding")
    binding = await capacity_binding_for_listing(db, ctx.listing_id)
    runtime = capacity or build_capacity_runtime(lambda: db)
    reservation = await runtime.release(
        binding,
        capacity_reservation_id=str(ctx.capacity_reservation_id or ""),
        deal_ref={"escrow_uid": ctx.escrow_uid} if ctx.escrow_uid else None,
        failure_reason=ctx.reason,
    )
    if reservation is not None:
        result.capacity_reservation_id = reservation.get("capacity_reservation_id")
        result.state = "released"
        result.resource_id = reservation.get("resource_id")
        result.gpu_count = reservation.get("allocated_gpu_count")
        home_site = next(iter(remote_site_clients(runtime.client())), None)
        reopened: list[str] = []
        if home_site is not None:
            reopened = closed_available_listing_ids(
                db.db_path,
                home_site=home_site,
                member_availability=await capacity_availability(runtime.client()),
            )
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

    thread = await _load_thread_for_escrow(db, ctx.escrow_uid) or {}
    try:
        Identity.model_validate(thread.get("buyer_principal"))
    except (TypeError, ValueError):
        return {
            "action": "refund",
            "status": "skipped",
            "reason": "buyer_principal_unknown",
        }
    buyer_evm_address = thread.get("buyer_evm_address")
    if not buyer_evm_address:
        return {
            "action": "refund",
            "status": "skipped",
            "reason": "buyer_evm_address_unknown",
        }

    result = await _refund_from_escrow_proposal(
        db,
        ctx=ctx,
        listing_id=listing_id,
        buyer_evm_address=buyer_evm_address,
        thread=thread,
    )
    if result is None:
        return {"action": "refund", "status": "skipped", "reason": "proposal_unknown"}
    return result


def _context_model(context: dict[str, Any]) -> FulfillmentFailureContext:
    fields = FulfillmentFailureContext.__dataclass_fields__
    return FulfillmentFailureContext(**{name: context.get(name) for name in fields})


def _result_from_context(context: dict[str, Any]) -> FulfillmentFailurePolicyResult:
    return FulfillmentFailurePolicyResult(
        capacity_reservation_id=context.get("capacity_reservation_id"),
        state=context.get("state"),
        resource_id=context.get("resource_id"),
        gpu_count=context.get("gpu_count"),
        resource_state=context.get("resource_state"),
        reopened_listing_ids=list(context.get("reopened_listing_ids") or []),
    )


_ACTIVE_FAILURE_STATE: ContextVar[dict[str, Any] | None] = ContextVar(
    "vm_active_failure_state",
    default=None,
)


def _action_context(context: dict[str, Any]) -> dict[str, Any]:
    return _ACTIVE_FAILURE_STATE.get() or context


async def _release_capacity_handler(
    db: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    state = _action_context(context)
    released = await _release_capacity(
        db,
        _context_model(state),
        state.get("_capacity_client"),
    )
    state.update(
        {
            "capacity_reservation_id": released.capacity_reservation_id,
            "state": released.state,
            "resource_id": released.resource_id,
            "gpu_count": released.gpu_count,
            "resource_state": released.resource_state,
            "reopened_listing_ids": released.reopened_listing_ids,
        }
    )
    return {"status": "ok"}


async def _emit_event_handler(
    _db: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    state = _action_context(context)
    stage_event(
        "fulfillment",
        "failed",
        **_failure_payload(_context_model(state), _result_from_context(state)),
    )
    return {"status": "ok"}


async def _webhook_handler(
    _db: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    state = _action_context(context)
    return await _send_webhook(
        _failure_payload(_context_model(state), _result_from_context(state))
    )


async def _refund_handler(
    db: Any,
    context: dict[str, Any],
) -> dict[str, Any]:
    state = _action_context(context)
    return await _refund(
        db,
        _context_model(state),
        state.get("listing_id"),
    )


_VM_FAILURE_POLICY = FailurePolicy(
    lambda: _configured_failure_actions_source(),
    {
        "release_capacity": _release_capacity_handler,
        "emit_event": _emit_event_handler,
        "webhook": _webhook_handler,
        "refund": _refund_handler,
    },
)


async def apply_fulfillment_failure_policy(
    db: Any,
    ctx: FulfillmentFailureContext,
    *,
    capacity: Any | None = None,
) -> FulfillmentFailurePolicyResult:
    context = dict(ctx.__dict__)
    context["listing_id"] = await _resolve_listing_id(db, ctx)
    if capacity is not None:
        context["_capacity_client"] = capacity
    token = _ACTIVE_FAILURE_STATE.set(context)
    try:
        dispatched = await _VM_FAILURE_POLICY.apply(db, context)
    finally:
        _ACTIVE_FAILURE_STATE.reset(token)
    result = _result_from_context(context)
    result.actions = dispatched.actions
    return result
