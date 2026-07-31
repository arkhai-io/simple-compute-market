"""API-credits fulfillment orchestration.

The token analog of ``fulfill_vm_obligation``, much smaller because the
deliverable is a ledger write, not a machine: one issuance call against
the credits service (which commits the negotiation-time quota hold —
open-ended, credits don't expire — or reserves fresh, idempotent on the
escrow uid), then the on-chain fulfillment obligation. The bearer
secret never goes on chain; it returns to the buyer once through the
settle-status credentials channel.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from domains.apicredits.settlement.credits_client import (
    CreditsServiceClient,
    CreditsServiceError,
)

logger = logging.getLogger(__name__)

StageEventFn = Callable[..., Any]
ApplyFailurePolicyFn = Callable[..., Awaitable[None]]


def encode_credit_fulfillment(
    *,
    offer_resource: dict[str, Any],
    key_id: str,
    quantity: int,
) -> str:
    """The seller's fulfillment obligation payload (public — no secret)."""
    return json.dumps({
        "kind": "api_credits.v1",
        "service_name": offer_resource.get("service_name"),
        "base_url": offer_resource.get("base_url"),
        "key_id": key_id,
        "quantity": int(quantity),
    })


async def _submit_token_fulfillment(
    *,
    client: Any | None,
    escrow_uid: str,
    payload: str,
) -> str:
    """Submit the fulfillment on-chain, or a simulated id in demo mode.

    Submission only — arbitration and collection are the claims
    engine's job, exactly as in the VM flow.
    """
    if not client:
        fulfillment_uid = f"fulfill_{uuid.uuid4()}"
        logger.info(
            "[ALKAHEST] (Simulated) Fulfilled token obligation without "
            "on-chain client."
        )
        return fulfillment_uid

    from market_alkahest.txlock import chain_tx_lock

    async with chain_tx_lock(None):
        fulfillment_uid = await client.string_obligation.do_obligation(
            payload,
            escrow_uid,
        )
    logger.info("[ALKAHEST] Fulfilled token obligation with on-chain client.")
    return fulfillment_uid


async def fulfill_api_credits_obligation(
    *,
    client: Any | None,
    escrow_uid: str,
    offer_resource: dict[str, Any],
    quantity: int,
    key_mode: str = "new",
    key_id: str | None = None,
    buyer_wallet: str | None = None,
    listing_id: str | None = None,
    credits_client: CreditsServiceClient | None = None,
    service_url: str | None = None,
    admin_key: str | None = None,
    stage_event: StageEventFn,
    apply_failure_policy: ApplyFailurePolicyFn | None = None,
    held_reservation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue credits and submit settlement fulfillment.

    ``held_reservation`` is the TTL soft hold the negotiation's
    acceptance placed; its capacity_reservation_id rides the issuance call so the
    credits service commits that hold (open-ended) instead of racing a
    fresh reserve. The service is the single writer for quota + grant —
    a partial failure between issuance and the on-chain obligation is
    rolled back through the same admin surface.
    """
    capacity_reservation_id = (
        str(held_reservation.get("capacity_reservation_id"))
        if held_reservation and held_reservation.get("capacity_reservation_id")
        else None
    )
    resource_id = offer_resource.get("resource_id")
    if credits_client is None:
        if service_url is None or admin_key is None:
            raise ValueError(
                "credits_client or service_url/admin_key is required"
            )
        credits_client = CreditsServiceClient(service_url, admin_key)

    async def _fail(reason: str, message: str) -> dict[str, Any]:
        if apply_failure_policy is not None:
            try:
                await apply_failure_policy(
                    capacity_reservation_id=capacity_reservation_id,
                    escrow_uid=escrow_uid,
                    listing_id=listing_id,
                    resource_id=resource_id,
                    reason=reason,
                    message=message,
                    source="settlement_issuance",
                )
            except Exception as policy_err:
                logger.warning(
                    "[FULFILLMENT_POLICY] Failed to apply issuance failure "
                    "policy for escrow %s: %s", escrow_uid, policy_err,
                )
        stage_event(
            "provision", "failed",
            escrow_uid=escrow_uid,
            listing_id=listing_id,
            resource_id=resource_id,
            error=message,
        )
        return {
            "status": "error",
            "message": message,
            "escrow_uid": escrow_uid,
        }

    try:
        issuance = await credits_client.submit_credit_issuance(
            escrow_uid=escrow_uid,
            quantity=quantity,
            key_mode=key_mode,
            key_id=key_id,
            buyer_wallet=buyer_wallet,
            capacity_reservation_id=capacity_reservation_id,
            resource_id=str(resource_id) if resource_id else None,
        )
    except CreditsServiceError as error:
        return await _fail(error.reason, f"Issuance refused: {error}")
    except Exception as error:
        return await _fail("issuance_unreachable", f"Issuance failed: {error}")

    issued_key_id = str(issuance.get("key_id"))
    stage_event(
        "provision", "credits_issued",
        escrow_uid=escrow_uid,
        listing_id=listing_id,
        resource_id=resource_id,
        key_id=issued_key_id,
        quantity=int(issuance.get("quantity") or quantity),
        balance=issuance.get("balance"),
        capacity_reservation_id=issuance.get("capacity_reservation_id") or capacity_reservation_id,
        already_issued=bool(issuance.get("already_issued")),
    )

    payload = encode_credit_fulfillment(
        offer_resource=offer_resource,
        key_id=issued_key_id,
        quantity=quantity,
    )
    try:
        fulfillment_uid = await _submit_token_fulfillment(
            client=client,
            escrow_uid=escrow_uid,
            payload=payload,
        )
    except Exception as error:
        rollback = await credits_client.rollback_issuance(
            escrow_uid=escrow_uid,
            issuance=issuance,
            key_mode=key_mode,
        )
        stage_event(
            "settlement", "failed_after_issuance",
            escrow_uid=escrow_uid,
            listing_id=listing_id,
            key_id=issued_key_id,
            rollback=rollback,
            error=str(error),
        )
        return {
            "status": "error",
            "message": f"On-chain fulfillment failed after issuance: {error}",
            "escrow_uid": escrow_uid,
        }

    stage_event(
        "provision", "fulfilled",
        listing_id=listing_id,
        escrow_uid=escrow_uid,
        fulfillment_uid=fulfillment_uid,
        resource_id=resource_id,
        key_id=issued_key_id,
        quantity=quantity,
    )
    credentials: dict[str, Any] = {
        "key_id": issued_key_id,
        "base_url": offer_resource.get("base_url"),
        "balance": issuance.get("balance"),
    }
    if issuance.get("secret"):
        credentials["secret"] = issuance["secret"]
    return {
        "status": "fulfilled",
        "message": "API-token obligation fulfilled",
        "escrow_uid": escrow_uid,
        "fulfillment_uid": fulfillment_uid,
        "connection_details": payload,
        "tenant_credentials": credentials,
    }
