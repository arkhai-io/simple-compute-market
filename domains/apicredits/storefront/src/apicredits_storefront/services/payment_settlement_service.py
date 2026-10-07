"""Receipt-gated API-credit issuance and seller refunds for Arkhai payments.

Credits are issued only after the exact accepted Agreement has a matching signed
receipt. The normal deal flow never refunds: a failed issuance is recorded as
failed, and a refund happens only on the seller's request or through the
seller's opt-in ``refund`` failure action. Settlement and refund for one deal
serialize on a per-negotiation lock so a recorded ``refunded`` state is final.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    MandatePolicyError,
    NotPaid,
    NothingToReverse,
    PaymentSellerStage,
    PaymentSettlementData,
    PaymentsUnavailable,
    ReceiptInvalid,
    ReceiptPending,
    ReceiptUnavailable,
    Refunded,
)
from market_core.schemas import Agreement
from market_identity import Identity

from apicredits_storefront.domain_runtime import (
    serialize_api_credit_settlement,
    serialize_api_credit_settlement_start,
)
from apicredits_storefront.services.payment_selection import (
    agreement_bytes as _agreement_bytes,
    selects_payments,
)

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}


class PaymentSettlementError(RuntimeError):
    """A settlement or refund refusal carrying the HTTP status the route returns."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class PaymentSettleResult:
    status_code: int
    payload: dict[str, Any] = field(default_factory=dict)


class ApiCreditPaymentSettlementService:
    def __init__(self, *, db: Any, composition: Any, stage: PaymentSellerStage) -> None:
        self.db = db
        self.composition = composition
        self.stage = stage

    def _accepted(
        self, negotiation_id: str, thread: Mapping[str, Any] | None
    ) -> tuple[dict[str, Any], PaymentSettlementData, Identity, Identity]:
        if not thread or thread.get("terminal_state") != "success":
            raise PaymentSettlementError(409, "accepted negotiation is unavailable")
        raw = _agreement_bytes(thread)
        if raw is None:
            raise PaymentSettlementError(409, "accepted Agreement is unavailable")
        try:
            agreement, data = self.stage.accepted(raw, thread.get("settlement_data"))
            accepted = Agreement.model_validate(agreement)
            buyer = Identity.model_validate(thread.get("buyer_principal"))
            seller = Identity.model_validate(thread.get("seller_principal"))
        except (MandatePolicyError, TypeError, ValueError) as exc:
            raise PaymentSettlementError(409, "accepted payment state is invalid") from exc
        if (
            accepted.negotiation_id != negotiation_id
            or Identity.model_validate(accepted.buyer) != buyer
            or Identity.model_validate(accepted.seller) != seller
        ):
            raise PaymentSettlementError(409, "Agreement parties or negotiation do not match")
        return agreement, data, buyer, seller

    @staticmethod
    def _payload(
        row: Mapping[str, Any] | None,
        *,
        negotiation_id: str,
        data: PaymentSettlementData,
        buyer: Identity,
        seller: Identity,
        status: str | None = None,
        retryable: bool = False,
        start: bool = False,
    ) -> dict[str, Any]:
        base = dict(row or {"escrow_uid": negotiation_id, "negotiation_id": negotiation_id})
        if status is not None:
            base["status"] = status
        serialized = (
            serialize_api_credit_settlement_start(base)
            if start
            else serialize_api_credit_settlement(base)
        )
        serialized.update(
            negotiation_id=negotiation_id,
            escrow_uid=negotiation_id,
            settlement_ref=data.transaction_id,
            retryable=retryable,
            buyer_principal=buyer.model_dump(mode="json"),
            seller_principal=seller.model_dump(mode="json"),
        )
        if status is not None:
            serialized["status"] = status
        return serialized

    async def settle(
        self, negotiation_id: str, *, buyer_principal: Identity, seller_principal: Identity
    ) -> PaymentSettleResult:
        async with _locks.setdefault(negotiation_id, asyncio.Lock()):
            thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            agreement, data, buyer, seller = self._accepted(negotiation_id, thread)
            if buyer != buyer_principal or seller != seller_principal:
                raise PaymentSettlementError(403, "settlement parties do not match negotiation")

            def payload(row, **kwargs):
                return self._payload(
                    row, negotiation_id=negotiation_id, data=data, buyer=buyer,
                    seller=seller, **kwargs,
                )

            existing = await self.db.load_escrow(escrow_uid=negotiation_id)
            if existing is not None and existing.get("status") == "refunded":
                return PaymentSettleResult(200, payload(existing, status="refunded"))
            if existing is not None and existing.get("status") in ("ready", "failed"):
                return PaymentSettleResult(200, payload(existing))

            outcome = await self.stage.check_receipt(agreement, data)
            if isinstance(outcome, ReceiptPending):
                return PaymentSettleResult(
                    202, payload(None, status="pending", retryable=True, start=True)
                )
            if isinstance(outcome, ReceiptUnavailable):
                raise PaymentSettlementError(503, "payments service is unavailable")
            if isinstance(outcome, ReceiptInvalid):
                logger.error(
                    "payment receipt for %s does not verify: %s", negotiation_id, outcome.reason
                )
                raise PaymentSettlementError(409, "payments receipt does not prove this Agreement")
            try:
                await self.stage.deposit_if_advertised(agreement, data)
            except PaymentsUnavailable as exc:
                raise PaymentSettlementError(503, "payments Agreement deposit is unavailable") from exc

            terms = await self.db.load_credit_terms(negotiation_id=negotiation_id)
            listing_id = thread.get("our_listing_id")
            order = await self.db.load_listing(listing_id=listing_id) if listing_id else None
            if not terms or not order:
                raise PaymentSettlementError(409, "credit provisioning terms are unavailable")
            fulfillment = self.composition.domain.fulfillment
            if fulfillment is None:
                raise PaymentSettlementError(503, "API-credit fulfillment is unavailable")
            if existing is None:
                await self.db.insert_escrow(
                    escrow_uid=negotiation_id,
                    negotiation_id=negotiation_id,
                    chain_name=None,
                    escrow_address=None,
                    is_primary=True,
                    status="provisioning",
                )
            try:
                result = await fulfillment.fulfill(
                    client=None,
                    escrow_uid=negotiation_id,
                    order=order,
                    quantity=int(terms["quantity"]),
                    key_mode=str(terms.get("key_mode") or "new"),
                    key_id=terms.get("key_id"),
                    buyer_principal=buyer,
                    listing_id=listing_id,
                    negotiation_id=negotiation_id,
                    mechanism=ARKHAI_PAYMENTS_MECHANISM,
                    authoritative_gate="payments_receipt_verified",
                )
            except Exception as exc:
                # An unknown issuance outcome stays retryable under the same
                # grant identity; it must not be recorded as a failure.
                logger.warning(
                    "API-credit issuance for payment %s is retryable after error: %s",
                    negotiation_id,
                    exc,
                )
                result = {"status": "pending", "message": f"Credit issuance outcome is uncertain: {exc}"}

            current = await self.db.load_escrow(escrow_uid=negotiation_id)
            if current is not None and current.get("status") == "refunded":
                return PaymentSettleResult(200, payload(current, status="refunded"))
            if result.get("status") == "fulfilled":
                await self.db.update_escrow(
                    escrow_uid=negotiation_id,
                    status="ready",
                    fulfillment_uid=result.get("fulfillment_uid"),
                    connection_details=result.get("connection_details"),
                    tenant_credentials=(
                        json.dumps(result["tenant_credentials"])
                        if isinstance(result.get("tenant_credentials"), Mapping)
                        else None
                    ),
                )
            elif result.get("status") == "pending":
                pending = payload(current, status="provisioning", retryable=True, start=True)
                pending["reason"] = result.get("message")
                return PaymentSettleResult(202, pending)
            else:
                await self.db.update_escrow(
                    escrow_uid=negotiation_id,
                    status="failed",
                    reason=str(result.get("message") or "credit issuance failed"),
                )
            row = await self.db.load_escrow(escrow_uid=negotiation_id)
            return PaymentSettleResult(200, payload(row))

    async def refund(self, negotiation_id: str) -> PaymentSettleResult:
        """Reverse the deal's held payment at the seller operator's request."""

        async with _locks.setdefault(negotiation_id, asyncio.Lock()):
            return await self._refund(negotiation_id, require_undelivered=False)

    async def refund_before_delivery(self, negotiation_id: str) -> dict[str, Any]:
        """Reverse a payment deal that failed before delivery, for the refund failure action.

        Issuance failure runs this from inside ``settle``, which already holds the
        deal's lock, so it must not take the lock again.
        """

        try:
            result = await self._refund(negotiation_id, require_undelivered=True)
        except PaymentSettlementError as exc:
            return {"action": "refund", "status": "failed", "reason": exc.detail}
        status = result.payload.get("status")
        return {
            "action": "refund",
            "status": "refunded" if status == "refunded" else "skipped",
            "escrow_kind": ARKHAI_PAYMENTS_MECHANISM,
            "settlement_ref": result.payload.get("settlement_ref"),
        }

    async def _refund(self, negotiation_id: str, *, require_undelivered: bool) -> PaymentSettleResult:
        thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if not thread or thread.get("terminal_state") != "success":
            raise PaymentSettlementError(404, "accepted negotiation not found")
        if not selects_payments(thread):
            raise PaymentSettlementError(409, "this settlement mechanism refunds through its own path")
        agreement, data, _buyer, _seller = self._accepted(negotiation_id, thread)
        refunded = {
            "negotiation_id": negotiation_id,
            "settlement_ref": data.transaction_id,
            "status": "refunded",
        }
        existing = await self.db.load_escrow(escrow_uid=negotiation_id)
        if existing is not None and existing.get("status") == "refunded":
            return PaymentSettleResult(200, refunded)
        if require_undelivered and existing is not None and existing.get("status") == "ready":
            return PaymentSettleResult(200, dict(refunded, status="ready"))
        outcome = await self.stage.reverse(agreement, data)
        if isinstance(outcome, NotPaid):
            raise PaymentSettlementError(409, "no verified payment exists to refund")
        if isinstance(outcome, NothingToReverse):
            raise PaymentSettlementError(409, "nothing left to reverse")
        if not isinstance(outcome, Refunded):
            raise PaymentSettlementError(503, "payments service is unavailable")
        if existing is None:
            await self.db.insert_escrow(
                escrow_uid=negotiation_id,
                negotiation_id=negotiation_id,
                chain_name=None,
                escrow_address=None,
                is_primary=True,
                status="refunded",
            )
        else:
            await self.db.update_escrow(escrow_uid=negotiation_id, status="refunded")
        return PaymentSettleResult(200, refunded)


__all__ = [
    "ApiCreditPaymentSettlementService",
    "PaymentSettleResult",
    "PaymentSettlementError",
    "selects_payments",
]
