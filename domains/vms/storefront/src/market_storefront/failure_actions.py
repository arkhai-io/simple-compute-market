"""VM-owned effects injected into the shared ordered failure policy."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from core_storefront.stage_log import stage_event
from market_alkahest.alkahest import get_escrow_codec_for
from market_alkahest.plans import escrow_terms_from_settlement_plan
from market_alkahest.schemas import EscrowTerms
from arkhai_vms_listings.reconciler import (
    closed_available_listing_ids,
)
from market_capacity_publication import (
    CapacityBindingError,
    SiteProjectionState,
    capacity_availability,
    remote_site_clients,
)
from market_identity import Identity
from market_settlement_runtime import FailurePolicy

import market_storefront.container as _container

from market_storefront.services.capacity_client import (
    build_capacity_runtime,
    capacity_binding_for_listing,
    site_capacity_buckets,
    site_pool_projection,
)
from market_storefront.services.shape_feasibility import vm_shape_feasibility
from market_storefront.utils.config import (
    get_evm_wallet_private_key,
    settings,
)

logger = logging.getLogger(__name__)


DEFAULT_FAILURE_ACTIONS = ("release_capacity", "emit_event")


@dataclass(frozen=True)
class FulfillmentFailureContext:
    capacity_reservation_id: str | None = None
    escrow_uid: str | None = None
    negotiation_id: str | None = None
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
        "negotiation_id": ctx.negotiation_id,
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


async def _load_failed_thread(
    db: Any, ctx: FulfillmentFailureContext
) -> dict[str, Any] | None:
    """The accepted thread of the failed deal, by negotiation or by its escrow."""
    if not hasattr(db, "load_negotiation_thread_row"):
        return None
    negotiation_id = ctx.negotiation_id
    if not negotiation_id and ctx.escrow_uid and hasattr(db, "load_escrow"):
        escrow = await db.load_escrow(escrow_uid=ctx.escrow_uid)
        negotiation_id = (escrow or {}).get("negotiation_id")
    if not negotiation_id:
        return None
    return await db.load_negotiation_thread_row(negotiation_id=negotiation_id)


def _accepted_escrow_obligation(
    plan: Any, *, chain_name: str, escrow_address: str
) -> EscrowTerms:
    """The accepted plan's one Alkahest obligation on this escrow's contract."""
    if not isinstance(plan, dict):
        raise ValueError("the negotiation records no accepted settlement plan")
    matches = [
        terms
        for terms in escrow_terms_from_settlement_plan(plan)
        if terms.chain_name == chain_name
        and terms.escrow_contract.lower() == escrow_address.lower()
    ]
    if len(matches) != 1:
        raise ValueError(
            "the accepted settlement plan holds no single obligation on escrow "
            f"{escrow_address!r} of chain {chain_name!r}"
        )
    return matches[0]


async def _refund_from_escrow_proposal(
    db: Any,
    *,
    ctx: FulfillmentFailureContext,
    listing_id: str,
    buyer_evm_address: str,
    thread: dict[str, Any],
) -> dict[str, Any] | None:
    # Only the accepted proposal carries the release condition the seller
    # authorized and the escrow was created under; the buyer's opening is not
    # a substitute, so a deal that recorded none is refused rather than refunded
    # from it.
    settlement_data = thread.get("settlement_data")
    proposal_raw = (
        settlement_data.get("accepted_escrow_proposal")
        if isinstance(settlement_data, dict)
        else None
    )
    if not isinstance(proposal_raw, dict):
        if isinstance(thread.get("buyer_escrow_proposal"), dict):
            return {
                "action": "refund",
                "status": "failed",
                "reason": "accepted_escrow_proposal_unavailable",
            }
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

    # A refund returns the escrow's token and amount, which the accepted plan
    # recorded when the deal was accepted; it is read from there rather than
    # materialized again, so a listing changed since acceptance cannot block it.
    try:
        terms = _accepted_escrow_obligation(
            thread.get("settlement_plan"),
            chain_name=chain_name,
            escrow_address=escrow_address,
        )
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
    site_projections: SiteProjectionState | None = None,
) -> FulfillmentFailurePolicyResult:
    """Release failed capacity at the listing's exact recorded site.

    Once the site has released the reservation, nothing after it may fail the
    release: the reopen it reports is best-effort, refreshed from
    ``site_projections`` when one is given and skipped when not.
    """
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
        deal_ref=(
            {"negotiation_id": ctx.negotiation_id}
            if ctx.negotiation_id
            else {"escrow_uid": ctx.escrow_uid}
            if ctx.escrow_uid
            else None
        ),
        failure_reason=ctx.reason,
        failure_message=ctx.message,
    )
    if reservation is not None:
        result.capacity_reservation_id = reservation.get("capacity_reservation_id")
        result.state = "released"
        result.resource_id = reservation.get("resource_id")
        result.gpu_count = reservation.get("allocated_gpu_count")
        reopened: list[str] = []
        if site_projections is None:
            logger.warning(
                "[FAILURE] no site projection state; released %s reopens nothing",
                result.capacity_reservation_id,
            )
        elif remote_site_clients(runtime.client()):
            # The same source publication derives from, refreshed for the site
            # this release just changed, so a reopen here agrees with what
            # publication would keep open and reports this release's own effect.
            # The refresh reconciles inline, so it wakes nothing; a failed fetch
            # keeps the site's last generation and never raises.
            try:
                await site_projections.refresh_site(binding.site_id)
            except CapacityBindingError:
                logger.warning(
                    "[FAILURE] site %s holds no projection here; reopening from "
                    "what is held",
                    binding.site_id,
                )
            reopened = closed_available_listing_ids(
                db.db_path,
                member_availability=await capacity_availability(runtime.client()),
                site_pool_projection=site_pool_projection(site_projections),
                site_capacity_buckets=site_capacity_buckets(site_projections),
                shape_feasible=vm_shape_feasibility(),
                configured_sites=runtime.site_ids,
                admissibility_default=_container.resolved_admissibility_default,
            )
        for listing_id in reopened:
            await db.update_listing(
                listing_id=listing_id, status="open", reopened_by="reconciliation"
            )
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


def _accepted_mechanism(thread: dict[str, Any]) -> str | None:
    raw = thread.get("agreement_bytes")
    if not isinstance(raw, bytes):
        return None
    try:
        agreement = json.loads(raw)
    except ValueError:
        return None
    selected = agreement.get("settlement") if isinstance(agreement, dict) else None
    mechanism = selected.get("mechanism") if isinstance(selected, dict) else None
    return mechanism if isinstance(mechanism, str) else None


async def _refund(
    db: Any,
    ctx: FulfillmentFailureContext,
    listing_id: str | None,
) -> dict[str, Any]:
    thread = await _load_failed_thread(db, ctx) or {}
    mechanism = _accepted_mechanism(thread)
    if mechanism is None:
        # No accepted Agreement names a mechanism, so only the escrow the
        # failure carries can be refunded.
        return await refund_escrow_listing(db, ctx, listing_id, thread)
    # The accepted Agreement's seller entry owns how its deal is refunded; an
    # entry without a refund operation leaves the deal to its own path.
    composition = _container.resolved_settlement_composition
    if composition is None:
        return {"action": "refund", "status": "skipped", "reason": "settlement_unavailable"}
    entry = composition.seller_stages.get(mechanism)
    refund = getattr(entry, "refund_failed_delivery", None)
    if refund is None:
        return {"action": "refund", "status": "skipped", "reason": "refund_unsupported"}
    return await refund(
        db=db, ctx=ctx, listing_id=listing_id, thread=thread, composition=composition
    )


async def refund_escrow_listing(
    db: Any,
    ctx: FulfillmentFailureContext,
    listing_id: str | None,
    thread: dict[str, Any],
) -> dict[str, Any]:
    """Refund the buyer's escrowed tokens for a failed deal's listing."""
    if not listing_id:
        return {"action": "refund", "status": "skipped", "reason": "listing_id_unknown"}

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
        state.get("_site_projections"),
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
    site_projections: SiteProjectionState | None = None,
) -> FulfillmentFailurePolicyResult:
    context = dict(ctx.__dict__)
    context["listing_id"] = await _resolve_listing_id(db, ctx)
    if capacity is not None:
        context["_capacity_client"] = capacity
    if site_projections is not None:
        context["_site_projections"] = site_projections
    token = _ACTIVE_FAILURE_STATE.set(context)
    try:
        dispatched = await _VM_FAILURE_POLICY.apply(db, context)
    finally:
        _ACTIVE_FAILURE_STATE.reset(token)
    result = _result_from_context(context)
    result.actions = dispatched.actions
    return result
