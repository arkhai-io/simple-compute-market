"""Receipt-gated API-credit issuance and seller refunds for Arkhai payments.

Credits are issued only after the exact accepted Agreement has a matching signed
receipt. The normal deal flow never refunds: a failed issuance is recorded as
failed, and a refund happens only on the seller's request or through the
seller's opt-in ``refund`` failure action.

State lives in the domain's settlement-evidence and issuance-progress tables.
The verified receipt is recorded once as immutable evidence; later settle
calls re-verify that stored receipt rather than polling again, so recovery
survives an unavailable payments service. Issuance start and refund intent are
durable transitions on those tables, each one serialized write, so exactly one
decides whether issuance precedes a refund, across processes.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping
from typing import Any

from core_storefront.models.settle_models import (
    AgreementSettleResponse,
    RefundSettlementResponse,
)
from market_arkhai_payments import (
    MandatePolicyError,
    NothingToReverse,
    NotPaid,
    PaymentsBlocked,
    PaymentSellerStage,
    PaymentSettlementData,
    PaymentsUnavailable,
    ReceiptBlocked,
    ReceiptInvalid,
    ReceiptPending,
    ReceiptUnavailable,
    ReceiptVerified,
    ReconciliationPass,
    RefundBlocked,
    Refunded,
    reconcile_accepted_payments,
)
from market_core import SettlementEvidence
from market_identity import Identity

from apicredits_storefront.settlement_stages import (
    SettlementRefusal,
    SettleResult,
    accepted_agreement,
    persist_delivery,
    project_progress,
    settlement_evidence,
)

logger = logging.getLogger(__name__)

_REFUND_STATES = frozenset({"refunding", "refunded"})


class ApiCreditPaymentSettlementService:
    """Payment settlement for one storefront database under the seller's trusted policy.

    ``mechanism`` is the key the payment entry is registered under in the
    seller stage table; reconciliation selects accepted deals by it.
    """

    def __init__(
        self, *, db: Any, composition: Any, stage: PaymentSellerStage, mechanism: str
    ) -> None:
        self.db = db
        self.composition = composition
        self.stage = stage
        self.mechanism = mechanism

    def _accepted(
        self, negotiation_id: str, thread: Mapping[str, Any] | None
    ) -> tuple[Any, bytes, dict[str, Any], PaymentSettlementData, Identity, Identity]:
        if not thread or thread.get("terminal_state") != "success":
            raise SettlementRefusal(409, "accepted negotiation is unavailable")
        try:
            agreement, raw = accepted_agreement(thread)
            agreement_json, data = self.stage.accepted(raw, thread.get("settlement_data"))
            buyer = Identity.model_validate(thread.get("buyer_principal"))
            seller = Identity.model_validate(thread.get("seller_principal"))
        except (KeyError, MandatePolicyError, TypeError, ValueError) as exc:
            raise SettlementRefusal(409, "accepted payment state is invalid") from exc
        if agreement.negotiation_id != negotiation_id:
            raise SettlementRefusal(409, "Agreement parties or negotiation do not match")
        return agreement, raw, agreement_json, data, buyer, seller

    async def _payload(
        self,
        *,
        negotiation_id: str,
        data: PaymentSettlementData,
        buyer: Identity,
        seller: Identity,
        progress: Mapping[str, Any] | None = None,
        status: str | None = None,
        retryable: bool = False,
    ) -> dict[str, Any]:
        if progress is not None:
            payload = await project_progress(self.db, progress, owner=buyer)
        else:
            payload = {"escrow_uid": negotiation_id, "negotiation_id": negotiation_id}
        if status is not None:
            payload["status"] = status
        payload.update(
            negotiation_id=negotiation_id,
            escrow_uid=negotiation_id,
            settlement_ref=data.transaction_id,
            retryable=retryable,
            buyer_principal=buyer.model_dump(mode="json"),
            seller_principal=seller.model_dump(mode="json"),
        )
        # The neutral fields are a cross-domain contract; refuse to emit a
        # payload that would not parse as one.
        AgreementSettleResponse.model_validate(payload)
        return payload

    async def reconcile_once(self, *, limit: int = 100) -> ReconciliationPass:
        """Advance accepted payment deals a buyer has not settled, without the buyer.

        Takes deals with no verified receipt, credit issuance whose outcome is
        still open, and refunds left `refunding`; the same settle path a buyer's
        call takes advances each.
        """
        candidates = await self.db.list_unsettled_payment_negotiations(
            mechanism=self.mechanism, limit=limit
        )

        async def settle(negotiation_id: str) -> None:
            thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            await self.settle(
                negotiation_id,
                buyer_principal=Identity.model_validate(thread["buyer_principal"]),
                seller_principal=Identity.model_validate(thread["seller_principal"]),
            )

        return await reconcile_accepted_payments(candidates, settle, logger=logger)

    async def _verified_evidence(
        self,
        negotiation_id: str,
        *,
        agreement: Any,
        raw: bytes,
        agreement_json: Mapping[str, Any],
        data: PaymentSettlementData,
        existing: SettlementEvidence | None,
        refund: bool = False,
    ) -> SettlementEvidence | None:
        """The deal's verified receipt evidence, recording it on first verification.

        Returns None while the payments service has no transaction yet. Stored
        evidence is re-verified locally against the accepted Agreement and the
        current receipt pin; nothing new is persisted for an unverified receipt.
        """
        wire = data.to_wire()
        if existing is not None and existing.status == "verified":
            source = dict(existing.evidence["source"])
            receipt = source.pop("receipt", None)
            try:
                existing.validate_identity(
                    negotiation_id=negotiation_id,
                    mechanism=agreement.settlement.mechanism,
                    settlement_ref=data.transaction_id,
                )
                proven = (
                    existing.evidence["agreement_digest"] == hashlib.sha256(raw).hexdigest()
                    and source == wire
                    and receipt is not None
                    and self.stage.receipt_matches(receipt, agreement_json, data)
                )
            except ValueError:
                proven = False
            if not proven:
                logger.error("stored payment evidence for %s does not prove its Agreement", negotiation_id)
                raise SettlementRefusal(409, "payments evidence does not prove this Agreement")
            return existing
        outcome = await self.stage.check_receipt(agreement_json, data)
        if isinstance(outcome, ReceiptPending):
            if refund:
                raise SettlementRefusal(409, "no verified payment exists to refund")
            return None
        if refund and isinstance(outcome, ReceiptInvalid):
            raise SettlementRefusal(409, "no verified payment exists to refund")
        self._raise_for_unverified(negotiation_id, outcome)
        assert isinstance(outcome, ReceiptVerified)
        order = await self.db.load_listing(listing_id=agreement.listing_id)
        if not order:
            raise SettlementRefusal(409, "credit provisioning terms are unavailable")
        try:
            evidence = settlement_evidence(
                agreement,
                raw,
                reference=data.transaction_id,
                status="verified",
                source={
                    **wire,
                    "receipt": outcome.receipt.model_dump(mode="json", by_alias=True, exclude_none=True),
                },
                order=order,
            )
            return await self.db.save_settlement_evidence(evidence)
        except ValueError as exc:
            raise SettlementRefusal(409, "credit provisioning terms are invalid") from exc

    @staticmethod
    def _raise_for_unverified(negotiation_id: str, outcome: Any) -> None:
        if isinstance(outcome, ReceiptUnavailable):
            raise SettlementRefusal(503, "payments service is unavailable")
        if isinstance(outcome, ReceiptInvalid):
            logger.error(
                "payment receipt for %s does not verify: %s", negotiation_id, outcome.reason
            )
            raise SettlementRefusal(409, "payments receipt does not prove this Agreement")
        if isinstance(outcome, ReceiptBlocked):
            logger.error(
                "payment settlement for %s needs operator action: %s", negotiation_id, outcome.reason
            )
            raise SettlementRefusal(500, "payments integration needs operator action")

    async def settle(
        self, negotiation_id: str, *, buyer_principal: Identity, seller_principal: Identity
    ) -> SettleResult:
        thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        agreement, raw, agreement_json, data, buyer, seller = self._accepted(negotiation_id, thread)
        if buyer != buyer_principal or seller != seller_principal:
            raise SettlementRefusal(403, "settlement parties do not match negotiation")

        async def payload(progress: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
            return await self._payload(
                negotiation_id=negotiation_id, data=data, buyer=buyer, seller=seller,
                progress=progress, **kwargs,
            )

        evidence = await self.db.load_settlement_evidence(negotiation_id=negotiation_id)
        progress = await self.db.load_issuance_progress(reference=negotiation_id)
        if evidence is not None and evidence.status in _REFUND_STATES:
            if evidence.status == "refunding":
                await self._complete_refund(negotiation_id, agreement_json, data)
            return SettleResult(200, await payload(progress, status="refunded"))
        if progress is not None and progress["status"] in ("ready", "failed"):
            return SettleResult(200, await payload(progress))

        evidence = await self._verified_evidence(
            negotiation_id, agreement=agreement, raw=raw, agreement_json=agreement_json,
            data=data, existing=evidence,
        )
        if evidence is None:
            return SettleResult(202, await payload(status="pending", retryable=True))
        try:
            await self.stage.deposit_if_advertised(agreement_json, data)
        except PaymentsUnavailable as exc:
            raise SettlementRefusal(503, "payments Agreement deposit is unavailable") from exc
        except PaymentsBlocked as exc:
            logger.error("payment deposit for %s needs operator action: %s", negotiation_id, exc)
            raise SettlementRefusal(500, "payments integration needs operator action") from exc

        fulfillment = self.composition.domain.fulfillment
        if fulfillment is None:
            raise SettlementRefusal(503, "API-credit fulfillment is unavailable")
        if progress is None:
            progress = await self.db.save_issuance_progress(
                negotiation_id=negotiation_id, public_ref=negotiation_id, status="provisioning",
            )
        if not await self.db.claim_credit_delivery_start(negotiation_id=negotiation_id):
            # Refund intent was recorded first; issuance must not start.
            return SettleResult(200, await payload(progress, status="refunded"))
        try:
            result = await fulfillment.fulfill(
                evidence=evidence,
                retry_uncertain=True,
                db=self.db,
                credits_client=getattr(self.composition, "credits_client", None),
            )
        except Exception as exc:
            # An unknown issuance outcome stays retryable under the same grant
            # identity; it must not be recorded as a failure.
            logger.warning(
                "API-credit issuance for payment %s is retryable after error: %s",
                negotiation_id,
                exc,
            )
            result = {"status": "pending", "message": f"Credit issuance outcome is uncertain: {exc}"}

        current = await self.db.load_settlement_evidence(negotiation_id=negotiation_id)
        refunded = current is not None and current.status in _REFUND_STATES
        if result.get("status") == "fulfilled" or not refunded:
            # Credits issued before a refund are recorded beside it.
            progress = await persist_delivery(self.db, evidence, result, public_ref=negotiation_id)
        if refunded:
            return SettleResult(200, await payload(progress, status="refunded"))
        if progress["status"] == "provisioning":
            return SettleResult(202, await payload(progress, retryable=True))
        return SettleResult(200, await payload(progress))

    async def status(
        self, negotiation_id: str, *, buyer_principal: Identity, seller_principal: Identity
    ) -> SettleResult | None:
        """Re-drive an open payment deal and report it; None while nothing is recorded."""

        evidence = await self.db.load_settlement_evidence(negotiation_id=negotiation_id)
        progress = await self.db.load_issuance_progress(reference=negotiation_id)
        open_deal = not (
            (evidence is not None and evidence.status == "refunded")
            or (progress is not None and progress["status"] in ("ready", "failed"))
        )
        result: SettleResult | None = None
        if open_deal:
            try:
                result = await self.settle(
                    negotiation_id,
                    buyer_principal=buyer_principal,
                    seller_principal=seller_principal,
                )
            except SettlementRefusal as exc:
                if exc.status_code < 500:
                    raise
                logger.warning(
                    "Payment settlement retry for %s is pending: %s", negotiation_id, exc.detail
                )
        if result is not None and result.payload.get("status") != "pending":
            return result
        evidence = await self.db.load_settlement_evidence(negotiation_id=negotiation_id)
        progress = await self.db.load_issuance_progress(reference=negotiation_id)
        if evidence is None and progress is None:
            return None
        thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        _agreement, _raw, _json, data, buyer, seller = self._accepted(negotiation_id, thread)
        status = "refunded" if evidence is not None and evidence.status in _REFUND_STATES else None
        if progress is None and status is None:
            status = "provisioning"
        return SettleResult(
            200,
            await self._payload(
                negotiation_id=negotiation_id, data=data, buyer=buyer, seller=seller,
                progress=progress, status=status,
            ),
        )

    async def refund(self, negotiation_id: str) -> SettleResult:
        """Reverse the deal's held payment at the seller operator's request."""

        return await self._refund(negotiation_id, require_undelivered=False)

    async def refund_before_delivery(self, negotiation_id: str) -> dict[str, Any]:
        """Reverse a payment deal that failed before any issuance, for the refund failure action."""

        try:
            result = await self._refund(negotiation_id, require_undelivered=True)
        except SettlementRefusal as exc:
            return {"action": "refund", "status": "failed", "reason": exc.detail}
        status = result.payload.get("status")
        return {
            "action": "refund",
            "status": "refunded" if status == "refunded" else "skipped",
            "mechanism": self.mechanism,
            "settlement_ref": result.payload.get("settlement_ref"),
        }

    async def _refund(self, negotiation_id: str, *, require_undelivered: bool) -> SettleResult:
        thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if not thread or thread.get("terminal_state") != "success":
            raise SettlementRefusal(404, "accepted negotiation not found")
        agreement, raw, agreement_json, data, _buyer, _seller = self._accepted(negotiation_id, thread)
        refunded = {
            "negotiation_id": negotiation_id,
            "settlement_ref": data.transaction_id,
            "status": "refunded",
        }
        evidence = await self.db.load_settlement_evidence(negotiation_id=negotiation_id)
        progress = await self.db.load_issuance_progress(reference=negotiation_id)
        if evidence is not None and evidence.status == "refunded":
            return SettleResult(200, refunded)
        if require_undelivered and progress is not None and progress["status"] == "ready":
            return SettleResult(200, dict(refunded, status="ready"))
        if evidence is None or evidence.status != "refunding":
            # Refuse before recording intent when there is no payment to reverse,
            # so an unpaid deal is never left blocked by an abandoned refund.
            await self._verified_evidence(
                negotiation_id, agreement=agreement, raw=raw, agreement_json=agreement_json,
                data=data, existing=evidence, refund=True,
            )
        await self._complete_refund(negotiation_id, agreement_json, data)
        RefundSettlementResponse.model_validate(refunded)
        return SettleResult(200, refunded)

    async def _complete_refund(
        self, negotiation_id: str, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> None:
        """Record intent, reverse, then record the refund; safe to repeat after a crash."""

        try:
            intent = await self.db.record_credit_refund_intent(negotiation_id=negotiation_id)
        except ValueError as exc:
            raise SettlementRefusal(409, "no verified payment exists to refund") from exc
        if intent["status"] == "refunded":
            return
        outcome = await self.stage.reverse(agreement, data)
        if isinstance(outcome, (NotPaid, NothingToReverse)):
            await self.db.abandon_credit_refund_intent(
                negotiation_id=negotiation_id, prior_status=intent["status"]
            )
            raise SettlementRefusal(
                409,
                "no verified payment exists to refund"
                if isinstance(outcome, NotPaid)
                else "nothing left to reverse",
            )
        if isinstance(outcome, RefundBlocked):
            logger.error("refund for %s needs operator action: %s", negotiation_id, outcome.reason)
            raise SettlementRefusal(500, "payments integration needs operator action")
        if not isinstance(outcome, Refunded):
            raise SettlementRefusal(503, "payments service is unavailable")
        await self.db.complete_credit_refund(negotiation_id=negotiation_id)


__all__ = ["ApiCreditPaymentSettlementService"]
