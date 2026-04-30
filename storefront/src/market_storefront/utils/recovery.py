"""Pure helpers for recovery endpoints (claim / reclaim / arbitrate).

Same pattern as `refund.py`: validate + derive. Each function takes a
loaded order row + request payload and returns either
  ("ok", {...params...}) — caller should perform the on-chain action; or
  ("error", status_code, {"error": "..."}) — caller should respond 4xx.

Splitting the pure logic out keeps the unit-test surface small (no agent
bootstrap required) and keeps the HTTP handlers linear.
"""

from __future__ import annotations

from typing import Any


ValidationResult = tuple


def _validate_order_id(payload: dict) -> str:
    """Extract + validate order_id from a request body. Raises ValueError on malformed."""
    order_id = payload.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("Request must include non-empty 'order_id'")
    return order_id.strip()


def derive_claim_params(*, order: dict[str, Any] | None, payload: dict) -> ValidationResult:
    """Seller collects an escrow after delivering.

    Requires the order to carry both escrow_uid (the buyer's escrow) and
    maker_attestation (the seller's fulfillment attestation UID — set by
    fulfill_compute_obligation). Without the attestation, the on-chain
    collect call has no fulfillment to reference.

    Allows `payload.fulfillment_uid` to override the order's
    maker_attestation for cases where the DB got out of sync with the
    chain (e.g. the attestation landed but the agent crashed before
    persisting it).
    """
    order_id = _validate_order_id(payload)
    if not order:
        return ("error", 404, {"error": f"Order {order_id} not found on this agent"})

    if order.get("status") == "closed":
        return (
            "error",
            409,
            {"error": "Order already closed", "order_id": order_id, "status": "closed"},
        )

    escrow_uid = order.get("escrow_uid")
    if not escrow_uid:
        return (
            "error",
            400,
            {"error": f"Order {order_id} has no escrow_uid; nothing to claim"},
        )

    fulfillment_uid = payload.get("fulfillment_uid") or order.get("seller_attestation")
    if not fulfillment_uid:
        return (
            "error",
            400,
            {
                "error": (
                    f"Order {order_id} has no maker_attestation yet — fulfillment has not "
                    "completed. Pass 'fulfillment_uid' explicitly if the attestation is on-chain "
                    "but missing locally."
                ),
            },
        )

    return (
        "ok",
        {
            "order_id": order_id,
            "escrow_uid": escrow_uid,
            "fulfillment_uid": fulfillment_uid,
        },
    )


def derive_reclaim_params(*, order: dict[str, Any] | None, payload: dict) -> ValidationResult:
    """Buyer reclaims an expired escrow.

    On-chain, `reclaim_expired()` only succeeds after the escrow's
    expiration. We don't duplicate that check here (the node will reject
    the tx), but we do refuse when there is no escrow to reclaim or the
    order is already closed/reclaimed.
    """
    order_id = _validate_order_id(payload)
    if not order:
        return ("error", 404, {"error": f"Order {order_id} not found on this agent"})

    if order.get("status") in ("closed", "reclaimed", "refunded"):
        return (
            "error",
            409,
            {
                "error": f"Order already in terminal state '{order.get('status')}'",
                "order_id": order_id,
                "status": order.get("status"),
            },
        )

    escrow_uid = order.get("escrow_uid")
    if not escrow_uid:
        return (
            "error",
            400,
            {"error": f"Order {order_id} has no escrow_uid; nothing to reclaim"},
        )

    return (
        "ok",
        {
            "order_id": order_id,
            "escrow_uid": escrow_uid,
        },
    )


def derive_arbitrate_params(*, order: dict[str, Any] | None, payload: dict) -> ValidationResult:
    """Buyer records an oracle decision on the seller's fulfillment.

    Under the current RecipientArbiter-based escrow, this on-chain
    decision does NOT gate collection — the seller can collect from their
    fulfillment attestation alone. This endpoint is kept for:
      (a) debugging / auditing the oracle side of the flow, and
      (b) future re-introduction of an oracle-gated arbiter.

    Requires: the buyer's order, with a maker_attestation (the seller's
    fulfillment UID) to arbitrate. Caller may override `fulfillment_uid`
    for out-of-band arbitration.
    """
    order_id = _validate_order_id(payload)
    if not order:
        return ("error", 404, {"error": f"Order {order_id} not found on this agent"})

    fulfillment_uid = payload.get("fulfillment_uid") or order.get("seller_attestation")
    if not fulfillment_uid:
        return (
            "error",
            400,
            {
                "error": (
                    f"Order {order_id} has no maker_attestation and no fulfillment_uid in body; "
                    "nothing to arbitrate."
                ),
            },
        )

    decision_raw = payload.get("decision", True)
    if isinstance(decision_raw, str):
        decision = decision_raw.lower() in ("true", "1", "yes", "approve")
    else:
        decision = bool(decision_raw)

    return (
        "ok",
        {
            "order_id": order_id,
            "fulfillment_uid": fulfillment_uid,
            "escrow_uid": order.get("escrow_uid"),
            "oracle_address": order.get("oracle_address"),
            "decision": decision,
        },
    )
