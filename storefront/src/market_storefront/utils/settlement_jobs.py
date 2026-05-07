"""Polling-mode settlement for buyer-as-client flow.

The seller exposes:
    POST /settle/{escrow_uid}          — kick off provisioning
    GET  /settle/{escrow_uid}/status   — read status (status + receipt)

Rather than the legacy flow where the seller pushes a fulfillment
notification to the buyer, this module persists provisioning status in
the `settlement_jobs` table; the buyer polls the GET endpoint.

Status lifecycle:
    provisioning  → ready   (on successful fulfill + attestation)
    provisioning  → failed  (on provisioning error)

The background task is an asyncio.create_task; all it does is call the
existing fulfill_compute_obligation and then patch the row on result.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def start_settlement_job(
    *,
    escrow_uid: str,
    negotiation_id: str,
    ssh_public_key: str,
    sqlite_client: Any,
    alkahest_client: Any,
) -> dict[str, Any]:
    """Kick off provisioning for an already-on-chain escrow.

    Verifies the negotiation is terminal-success with agreed terms,
    locates the seller's order, **reads the on-chain escrow and asserts it
    matches the negotiated terms** (fail-closed; see
    ``escrow_verification.verify_escrow_for_settlement``), then inserts a
    settlement_jobs row and schedules the provisioning coroutine. Returns
    the job state immediately (status='provisioning' on first call, or the
    existing row verbatim if already kicked off — idempotent by escrow_uid).

    Raises:
        ValueError if the negotiation doesn't exist, isn't terminal-
            success, has no agreed_price, or the seller's order is gone
            from the local DB.
        EscrowVerificationError if the on-chain escrow does not match the
            negotiated terms (wrong token, insufficient amount, wrong
            recipient, expired, revoked, etc).
    """
    from market_storefront.utils.config import CONFIG
    from market_storefront.utils.escrow_verification import (
        verify_escrow_for_settlement,
    )

    thread = await sqlite_client.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    if not thread:
        raise ValueError(f"Unknown negotiation {negotiation_id}")
    if thread.get("terminal_state") != "success":
        raise ValueError(
            f"Negotiation {negotiation_id} is not terminal-success "
            f"(terminal_state={thread.get('terminal_state')!r})"
        )
    if thread.get("agreed_price") is None:
        raise ValueError(f"Negotiation {negotiation_id} has no agreed_price committed")

    our_listing_id = thread.get("our_listing_id")
    our_order_dict = await sqlite_client.load_listing(listing_id=our_listing_id) if our_listing_id else None
    if not our_order_dict:
        raise ValueError(
            f"Seller's order {our_listing_id!r} (from negotiation {negotiation_id}) "
            "is gone from the local DB"
        )

    # Fail-closed on-chain verification: the escrow must exist, be live,
    # and match the negotiated terms before we touch any local state or
    # provision a VM.  Raises EscrowVerificationError on mismatch; the
    # controller maps that to HTTP 400.
    duration_for_amount = (
        thread.get("agreed_duration_seconds")
        or thread.get("requested_duration_seconds")
        or our_order_dict.get("max_duration_seconds")
        or 3600
    )
    await verify_escrow_for_settlement(
        escrow_uid=escrow_uid,
        seller_wallet=CONFIG.agent_wallet_address or "",
        agreed_price=int(thread["agreed_price"]),
        agreed_duration_seconds=int(duration_for_amount),
        listing=our_order_dict,
        alkahest_client=alkahest_client,
        chain_name=CONFIG.chain_name,
        alkahest_address_config_path=CONFIG.alkahest_address_config_path,
    )

    inserted = await sqlite_client.insert_settlement_job(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        status="provisioning",
    )
    if not inserted:
        # Already running or finished — return current state, idempotent.
        existing = await sqlite_client.load_settlement_job(escrow_uid=escrow_uid)
        logger.info(
            "[SETTLE_JOB] Job already exists for escrow %s: status=%s",
            escrow_uid, (existing or {}).get("status"),
        )
        return existing or {}

    # Link escrow_uid to the seller's local order so recovery endpoints
    # (claim/reclaim/refund) and `market logs status` can tie fulfillment
    # back to this deal. Idempotent update_order call.
    try:
        await sqlite_client.update_listing(
            listing_id=our_listing_id,
            status="accepted",
            escrow_uid=escrow_uid,
        )
    except Exception as exc:
        logger.warning(
            "[SETTLE_JOB] Could not attach escrow_uid to order %s: %s",
            our_listing_id, exc,
        )

    # The buyer's lease ask was committed on the negotiation thread when
    # the round terminated `agreed`. Fall back to the listing's max
    # ceiling, then 1h, only for legacy threads from before duration
    # became buyer-supplied.
    duration_seconds = (
        thread.get("agreed_duration_seconds")
        or thread.get("requested_duration_seconds")
        or our_order_dict.get("max_duration_seconds")
        or 3600
    )

    asyncio.create_task(
        _run_settlement_job_bg(
            escrow_uid=escrow_uid,
            ssh_public_key=ssh_public_key,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
            duration_seconds=int(duration_seconds),
            sqlite_client=sqlite_client,
            alkahest_client=alkahest_client,
        )
    )

    return {
        "escrow_uid": escrow_uid,
        "negotiation_id": negotiation_id,
        "status": "provisioning",
    }


async def _run_settlement_job_bg(
    *,
    escrow_uid: str,
    ssh_public_key: str,
    listing_id: str,
    order_dict: dict[str, Any],
    duration_seconds: int,
    sqlite_client: Any,
    alkahest_client: Any,
) -> None:
    """Background coroutine: run fulfillment, patch the job row."""
    # Imported here so unit tests can mock fulfill_compute_obligation by
    # patching the symbol on this module.
    from market_storefront.utils.action_executor import fulfill_compute_obligation
    from market_storefront.utils.config import CONFIG

    try:
        result = await fulfill_compute_obligation(
            client=alkahest_client,
            escrow_uid=escrow_uid,
            ssh_public_key=ssh_public_key,
            oracle_address=CONFIG.agent_wallet_address,
            order=order_dict,
            duration_seconds=duration_seconds,
            listing_id=listing_id,
        )
    except Exception as exc:
        logger.exception("[SETTLE_JOB] fulfill_compute_obligation raised for %s", escrow_uid)
        await sqlite_client.update_settlement_job(
            escrow_uid=escrow_uid,
            status="failed",
            reason=f"provisioning_error: {exc}",
        )
        return

    status = (result or {}).get("status")
    if status == "fulfilled":
        await sqlite_client.update_settlement_job(
            escrow_uid=escrow_uid,
            status="ready",
            attestation_uid=result.get("fulfillment_uid") or result.get("seller_attestation"),
            connection_details=result.get("connection_details"),
            tenant_credentials=json.dumps(result.get("tenant_credentials"))
                if result.get("tenant_credentials") is not None else None,
        )
        logger.info("[SETTLE_JOB] Escrow %s provisioning complete", escrow_uid)
    else:
        reason = (result or {}).get("message") or f"status={status!r}"
        await sqlite_client.update_settlement_job(
            escrow_uid=escrow_uid,
            status="failed",
            reason=reason,
        )
        logger.warning(
            "[SETTLE_JOB] Escrow %s provisioning did not succeed: %s",
            escrow_uid, reason,
        )


def serialize_settlement_job(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a raw settlement_jobs row for the HTTP response.

    Deserializes tenant_credentials (stored as JSON text) and omits None
    fields so the response body is compact.
    """
    out: dict[str, Any] = {
        "escrow_uid": row.get("escrow_uid"),
        "negotiation_id": row.get("negotiation_id"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    for field in ("attestation_uid", "provisioning_job_id", "connection_details", "reason"):
        v = row.get(field)
        if v is not None:
            out[field] = v
    tc_raw = row.get("tenant_credentials")
    if tc_raw:
        try:
            out["tenant_credentials"] = json.loads(tc_raw)
        except Exception:
            out["tenant_credentials"] = tc_raw
    return out
