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

from service.schemas import EscrowProposal, ProvisionTerms

logger = logging.getLogger(__name__)


def _resolve_duration_seconds(thread: dict[str, Any], order_dict: dict[str, Any]) -> int:
    """Duration the buyer's lease was negotiated for.

    Falls back through the negotiation thread, the listing's advertised
    ceiling, and finally a 1h default. The fallback chain exists for
    legacy threads (pre-buyer-supplied duration) and missing-listing
    edge cases; new flows always have ``agreed_duration_seconds`` set
    when the round terminated ``agreed``.
    """
    return int(
        thread.get("agreed_duration_seconds")
        or thread.get("requested_duration_seconds")
        or order_dict.get("max_duration_seconds")
        or 3600
    )


def _resolve_compute_resource(order_dict: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort extraction of the listing's offer_resource as a dict.

    SQLite stores resources as JSON text; the listing-load path may
    have already deserialized it, or it may still be a string. None
    when the field is missing or unparseable — the resulting
    ``ProvisionTerms`` simply has no compute snapshot in that case.
    """
    raw = order_dict.get("offer_resource")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


async def start_settlement_job(
    *,
    escrow_uid: str,
    negotiation_id: str,
    ssh_public_key: str,
    sqlite_client: Any,
    alkahest_client: Any,
    chain_name: str,
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
    from market_storefront.utils.config import CHAINS, settings
    from market_storefront.utils.escrow_verification import (
        verify_escrow_for_settlement,
    )

    chain_cfg = CHAINS.get(chain_name)
    if chain_cfg is None:
        raise ValueError(
            f"chain {chain_name!r} is not configured on this storefront"
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

    # Single source of truth for what the seller commits to deliver.
    # Same shape the buyer will eventually send in the negotiate-init
    # request; for now built locally from the negotiation thread + listing.
    provision = ProvisionTerms(
        duration_seconds=_resolve_duration_seconds(thread, our_order_dict),
        ssh_public_key=ssh_public_key,
        compute_resource=_resolve_compute_resource(our_order_dict),
    )

    # Re-type the persisted proposal off the thread. The buyer published
    # this at /negotiate/new; we validated it and stored as JSON. None
    # for legacy threads (pre-step-7) — the verifier falls back to
    # listing-derived defaults in that case.
    proposal_raw = thread.get("buyer_escrow_proposal")
    proposal: EscrowProposal | None = None
    if isinstance(proposal_raw, dict):
        proposal = EscrowProposal.model_validate(proposal_raw)

    # Fail-closed on-chain verification: the escrow must exist, be live,
    # and match the negotiated terms before we touch any local state or
    # provision a VM.  Raises EscrowVerificationError on mismatch; the
    # controller maps that to HTTP 400.
    await verify_escrow_for_settlement(
        escrow_uid=escrow_uid,
        seller_wallet=settings.wallet.address or "",
        agreed_price=int(thread["agreed_price"]),
        agreed_duration_seconds=provision.duration_seconds,
        listing=our_order_dict,
        alkahest_client=alkahest_client,
        chain_name=chain_name,
        alkahest_address_config_path=chain_cfg.alkahest_address_config_path,
        escrow_proposal=proposal,
    )

    # Pin the (chain_name, escrow_address) the buyer's proposal selected; if
    # absent (legacy threads), fall back to the listing's first accepted
    # escrow. Multi-escrow deals (bond, penalty, etc.) get one row each, with
    # is_primary=1 on the payment lockup that drives provisioning.
    proposal_chain = proposal.chain_name if proposal is not None else None
    escrow_address = proposal.escrow_address if proposal is not None else None
    if proposal_chain is None or escrow_address is None:
        accepted = our_order_dict.get("accepted_escrows") or []
        if accepted and isinstance(accepted[0], dict):
            proposal_chain = proposal_chain or accepted[0].get("chain_name")
            escrow_address = escrow_address or accepted[0].get("escrow_address")
    # The DB row records the chain the escrow lives on — preserve the
    # caller's (proposal-derived) chain_name rather than the request-level
    # ``chain_name`` parameter, which should already agree but keep the
    # proposal as the source of truth.
    if proposal_chain and proposal_chain != chain_name:
        logger.warning(
            "[SETTLE_JOB] Proposal chain %r diverges from request chain %r; "
            "using proposal chain.", proposal_chain, chain_name,
        )

    inserted = await sqlite_client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name=proposal_chain or chain_name,
        escrow_address=escrow_address,
        is_primary=True,
        status="provisioning",
    )
    if not inserted:
        # Already running or finished — return current state, idempotent.
        existing = await sqlite_client.load_escrow(escrow_uid=escrow_uid)
        logger.info(
            "[SETTLE_JOB] Job already exists for escrow %s: status=%s",
            escrow_uid, (existing or {}).get("status"),
        )
        return existing or {}

    asyncio.create_task(
        _run_settlement_job_bg(
            escrow_uid=escrow_uid,
            provision=provision,
            listing_id=our_listing_id,
            order_dict=our_order_dict,
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
    provision: ProvisionTerms,
    listing_id: str,
    order_dict: dict[str, Any],
    sqlite_client: Any,
    alkahest_client: Any,
) -> None:
    """Background coroutine: run fulfillment, patch the job row."""
    # Imported here so unit tests can mock fulfill_compute_obligation by
    # patching the symbol on this module.
    from market_storefront.utils.action_executor import fulfill_compute_obligation
    from market_storefront.utils.config import settings

    try:
        result = await fulfill_compute_obligation(
            client=alkahest_client,
            escrow_uid=escrow_uid,
            ssh_public_key=provision.ssh_public_key,
            oracle_address=settings.wallet.address,
            order=order_dict,
            duration_seconds=provision.duration_seconds,
            listing_id=listing_id,
        )
    except Exception as exc:
        logger.exception("[SETTLE_JOB] fulfill_compute_obligation raised for %s", escrow_uid)
        await sqlite_client.update_escrow(
            escrow_uid=escrow_uid,
            status="failed",
            reason=f"provisioning_error: {exc}",
        )
        return

    status = (result or {}).get("status")
    if status == "fulfilled":
        await sqlite_client.update_escrow(
            escrow_uid=escrow_uid,
            status="ready",
            fulfillment_uid=result.get("fulfillment_uid"),
            connection_details=result.get("connection_details"),
            tenant_credentials=json.dumps(result.get("tenant_credentials"))
                if result.get("tenant_credentials") is not None else None,
        )
        logger.info("[SETTLE_JOB] Escrow %s provisioning complete", escrow_uid)
    else:
        reason = (result or {}).get("message") or f"status={status!r}"
        await sqlite_client.update_escrow(
            escrow_uid=escrow_uid,
            status="failed",
            reason=reason,
        )
        logger.warning(
            "[SETTLE_JOB] Escrow %s provisioning did not succeed: %s",
            escrow_uid, reason,
        )


def serialize_settlement_job(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a raw escrows row for the HTTP response.

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
    for field in (
        "fulfillment_uid",
        "chain_name",
        "escrow_address",
        "provisioning_job_id",
        "connection_details",
        "reason",
    ):
        v = row.get(field)
        if v is not None:
            out[field] = v
    if row.get("is_primary") is not None:
        out["is_primary"] = bool(row["is_primary"])
    tc_raw = row.get("tenant_credentials")
    if tc_raw:
        try:
            out["tenant_credentials"] = json.loads(tc_raw)
        except Exception:
            out["tenant_credentials"] = tc_raw
    return out
