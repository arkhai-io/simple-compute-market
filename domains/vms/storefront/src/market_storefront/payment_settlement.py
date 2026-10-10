"""Receipt-gated VM provisioning, negotiation-scoped retry, and seller refunds.

Refund state lives on the deal's settlement evidence. Delivery start is the
insert of the deal's delivery record, which requires ``verified`` evidence;
refund intent moves the evidence from ``verified`` to ``refunding``. Each is one
serialized write, so exactly one decides whether delivery precedes a refund. A
refund that wins stops delivery from starting; a delivery that wins completes
and is recorded beside the refund. The per-negotiation lock only keeps one
process's settlement and refund calls from interleaving.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    fulfill_domain,
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
    ReconciliationPass,
    RefundBlocked,
    Refunded,
    reconcile_accepted_payments,
)
from market_identity import Identity

from market_storefront.payment_repository import VmSettlementEvidenceConflict
from market_storefront.services.fulfillment_resume_runtime import (
    resume_incomplete_fulfillments_once,
)
from market_storefront.settlement_stages import (
    PaymentSettleResult,
    PaymentSettlementError,
    VmPaymentsSellerStage,
    vm_evidence,
)
from market_storefront.utils import config

logger = logging.getLogger(__name__)

_TERMINAL_DELIVERY = ("ready", "failed", "refunded")
_REFUND_STATES = ("refunding", "refunded")

__all__ = [
    "PaymentSettleResult",
    "PaymentSettlementError",
    "VmPaymentsCoordinator",
]


class VmPaymentsCoordinator:
    def __init__(self, *, domain: Any, db: Any, stage: PaymentSellerStage) -> None:
        self.domain = domain
        self.db = db
        self.stage = stage
        self.tasks: dict[str, asyncio.Task] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.owner = f"payments:{uuid.uuid4()}"
        # The mechanisms this coordinator settles are the seller-table entries
        # that settle through it, so reconciliation selects deals by the table.
        self.mechanisms = tuple(
            mechanism
            for mechanism, entry in domain.settlement.seller_stages.items()
            if isinstance(entry, VmPaymentsSellerStage)
        )

    def _lock(self, negotiation_id: str) -> asyncio.Lock:
        return self.locks.setdefault(negotiation_id, asyncio.Lock())

    def _entry(self, agreement: dict[str, Any]) -> Any:
        return self.domain.settlement.seller_stages[agreement["settlement"]["mechanism"]]

    async def stop(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _accepted(
        self, negotiation_id: str, thread: dict[str, Any]
    ) -> tuple[bytes, dict[str, Any], PaymentSettlementData]:
        raw = thread.get("agreement_bytes")
        if not isinstance(raw, bytes):
            raise PaymentSettlementError(409, "accepted Agreement bytes are unavailable")
        try:
            agreement, data = self.stage.accepted(raw, thread.get("settlement_data"))
            buyer = Identity.model_validate(thread["buyer_principal"])
            seller = Identity.model_validate(thread["seller_principal"])
            provision = normalize_vm_provision_terms(agreement.get("provision_terms"))
        except (MandatePolicyError, KeyError, TypeError, ValueError) as exc:
            raise PaymentSettlementError(409, "accepted payment state is invalid") from exc
        if (
            agreement["negotiation_id"] != negotiation_id
            or agreement["listing_id"] != thread["our_listing_id"]
            or agreement["buyer"] != buyer.model_dump(mode="json")
            or agreement["seller"] != seller.model_dump(mode="json")
            or str(agreement["amount"]) != str(thread["agreed_price"])
            or agreement["duration_seconds"] != thread["agreed_duration_seconds"]
            or not provision.ssh_public_key.strip()
        ):
            raise PaymentSettlementError(409, "accepted Agreement does not match negotiation")
        return raw, agreement, data

    @staticmethod
    def _neutral(
        negotiation_id: str,
        data: PaymentSettlementData,
        status: str,
        *,
        retryable: bool = False,
        row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(row or {})
        payload.update(
            negotiation_id=negotiation_id,
            escrow_uid=negotiation_id,
            settlement_ref=data.transaction_id,
            status=status,
            retryable=retryable,
        )
        return payload

    async def _save(self, evidence: Any) -> None:
        try:
            await self.db.save_vm_settlement_evidence(evidence)
        except VmSettlementEvidenceConflict as exc:
            raise PaymentSettlementError(409, str(exc)) from exc

    async def _record_verified(
        self,
        negotiation_id: str,
        raw: bytes,
        agreement: dict[str, Any],
        data: PaymentSettlementData,
        receipt: Any,
    ) -> Any:
        listing = await self.db.load_listing(listing_id=agreement["listing_id"])
        if not isinstance(listing, dict):
            raise PaymentSettlementError(409, "accepted listing is unavailable")
        record = self._entry(agreement).verified_evidence(
            raw=raw, order=listing, receipt=receipt, data=data
        )
        await self._save(record)
        return record

    async def start(self, negotiation_id: str, thread: dict[str, Any]) -> PaymentSettleResult:
        async with self._lock(negotiation_id):
            raw, agreement, data = self._accepted(negotiation_id, thread)
            entry = self._entry(agreement)
            record = await self.db.load_vm_settlement_evidence(negotiation_id=negotiation_id)
            if record is not None and record.status in _REFUND_STATES:
                return await self._refunded_result(negotiation_id, agreement, data, record)
            if record is not None and record.status == "verified":
                try:
                    entry.revalidate(evidence=record, thread=thread, verifier=self.stage)
                except ValueError as exc:
                    logger.error("stored payment receipt for %s no longer verifies", negotiation_id)
                    raise PaymentSettlementError(
                        409, "stored payment receipt does not prove this Agreement"
                    ) from exc
            else:
                outcome = await self.stage.check_receipt(agreement, data)
                if isinstance(outcome, ReceiptPending):
                    await self._save(
                        vm_evidence(
                            raw=raw,
                            mechanism=entry.mechanism,
                            reference=data.transaction_id,
                            status="pending",
                            source={"mandate": data.to_wire()["mandate"]},
                            facts={},
                        )
                    )
                    return PaymentSettleResult(
                        202, self._neutral(negotiation_id, data, "pending", retryable=True)
                    )
                if isinstance(outcome, ReceiptUnavailable):
                    raise PaymentSettlementError(503, "payments service is unavailable")
                if isinstance(outcome, ReceiptBlocked):
                    logger.error(
                        "payment settlement for %s needs operator action: %s",
                        negotiation_id,
                        outcome.reason,
                    )
                    raise PaymentSettlementError(500, "payments integration needs operator action")
                if isinstance(outcome, ReceiptInvalid):
                    logger.error(
                        "payment receipt for %s does not verify: %s", negotiation_id, outcome.reason
                    )
                    raise PaymentSettlementError(409, "payments receipt does not prove this Agreement")
                record = await self._record_verified(
                    negotiation_id, raw, agreement, data, outcome.receipt
                )
            try:
                await self.stage.deposit_if_advertised(agreement, data)
            except PaymentsUnavailable as exc:
                raise PaymentSettlementError(503, "payments Agreement deposit is unavailable") from exc
            except PaymentsBlocked as exc:
                logger.error("payment deposit for %s needs operator action: %s", negotiation_id, exc)
                raise PaymentSettlementError(500, "payments integration needs operator action") from exc
            binding = await self.db.load_thread_binding(negotiation_id=negotiation_id)
            if self.db.domain_registry.resolve(binding.binding) is not self.domain:
                raise PaymentSettlementError(409, "accepted domain binding disagrees with provisioning")
            existing = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
            if existing and existing["status"] in _TERMINAL_DELIVERY:
                return PaymentSettleResult(
                    200, self._neutral(negotiation_id, data, existing["status"], row=existing)
                )
            try:
                await self.db.insert_vm_delivery(negotiation_id=negotiation_id)
            except ValueError:
                # Another process recorded refund intent first; delivery must not start.
                current = await self.db.load_vm_settlement_evidence(negotiation_id=negotiation_id)
                if current is None or current.status not in _REFUND_STATES:
                    raise
                return await self._refunded_result(negotiation_id, agreement, data, current)
            task = self.tasks.get(negotiation_id)
            if task is None or task.done():
                self.tasks[negotiation_id] = asyncio.create_task(
                    self._provision(negotiation_id, agreement, binding, record)
                )
            row = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
            return PaymentSettleResult(
                202, self._neutral(negotiation_id, data, row["status"], row=row)
            )

    async def _refunded_result(
        self,
        negotiation_id: str,
        agreement: dict[str, Any],
        data: PaymentSettlementData,
        record: Any,
    ) -> PaymentSettleResult:
        if record.status == "refunding":
            await self._complete_refund(negotiation_id, agreement, data)
        row = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
        return PaymentSettleResult(
            200, self._neutral(negotiation_id, data, "refunded", row=row)
        )

    async def reconcile_once(self, *, limit: int = 100) -> ReconciliationPass:
        """Advance accepted payment deals a buyer has not settled, without the buyer.

        A deal with a delivery record belongs to the fulfillment resume sweep;
        this pass takes the deals before that point and refunds left
        ``refunding``.
        """
        candidates: list[str] = []
        for mechanism in self.mechanisms:
            candidates.extend(
                await self.db.list_unsettled_payment_negotiations(
                    mechanism=mechanism, limit=limit
                )
            )

        async def settle(negotiation_id: str) -> None:
            thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            await self.start(negotiation_id, thread)

        return await reconcile_accepted_payments(candidates[:limit], settle, logger=logger)

    async def refund(self, negotiation_id: str, thread: dict[str, Any]) -> PaymentSettleResult:
        """Reverse the deal's held payment at the seller operator's request."""

        async with self._lock(negotiation_id):
            return await self._refund_locked(negotiation_id, thread, require_undelivered=False)

    async def refund_before_delivery(self, negotiation_id: str) -> dict[str, Any]:
        """Reverse a payment deal that failed before any delivery, for the refund failure action."""

        thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if not isinstance(thread, dict):
            return {"action": "refund", "status": "skipped", "reason": "negotiation_unknown"}
        try:
            async with self._lock(negotiation_id):
                result = await self._refund_locked(negotiation_id, thread, require_undelivered=True)
        except PaymentSettlementError as exc:
            return {"action": "refund", "status": "failed", "reason": exc.detail}
        status = result.payload.get("status")
        agreement = json.loads(thread["agreement_bytes"])
        return {
            "action": "refund",
            "status": "refunded" if status == "refunded" else "skipped",
            "escrow_kind": agreement["settlement"]["mechanism"],
            "settlement_ref": result.payload.get("settlement_ref"),
        }

    async def _refund_locked(
        self, negotiation_id: str, thread: dict[str, Any], *, require_undelivered: bool
    ) -> PaymentSettleResult:
        raw, agreement, data = self._accepted(negotiation_id, thread)
        record = await self.db.load_vm_settlement_evidence(negotiation_id=negotiation_id)
        if record is not None and record.status == "refunded":
            return PaymentSettleResult(200, self._refund_payload(negotiation_id, data))
        if require_undelivered:
            delivery = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
            if delivery and delivery["status"] == "ready":
                return PaymentSettleResult(200, self._neutral(negotiation_id, data, "ready"))
        if record is None or record.status != "refunding":
            # Refuse before recording intent when there is no payment to reverse,
            # so an unpaid deal is never left blocked by an abandoned refund.
            current = await self.stage.check_receipt(agreement, data)
            if isinstance(current, (ReceiptPending, ReceiptInvalid)):
                raise PaymentSettlementError(409, "no verified payment exists to refund")
            if isinstance(current, ReceiptUnavailable):
                raise PaymentSettlementError(503, "payments service is unavailable")
            if isinstance(current, ReceiptBlocked):
                logger.error("refund for %s needs operator action: %s", negotiation_id, current.reason)
                raise PaymentSettlementError(500, "payments integration needs operator action")
            if record is None or record.status != "verified":
                # Refund state moves from verified evidence, so a payment the
                # seller has not yet recorded is recorded first.
                await self._record_verified(negotiation_id, raw, agreement, data, current.receipt)
        await self._complete_refund(negotiation_id, agreement, data)
        return PaymentSettleResult(200, self._refund_payload(negotiation_id, data))

    async def _complete_refund(
        self, negotiation_id: str, agreement: dict[str, Any], data: PaymentSettlementData
    ) -> None:
        """Record intent, reverse, then record the refund; safe to repeat after a crash."""

        try:
            prior = await self.db.record_vm_refund_intent(negotiation_id=negotiation_id)
        except ValueError as exc:
            raise PaymentSettlementError(409, "no verified payment exists to refund") from exc
        if prior == "refunded":
            return
        outcome = await self.stage.reverse(agreement, data)
        if isinstance(outcome, (NotPaid, NothingToReverse)):
            await self.db.abandon_vm_refund_intent(negotiation_id=negotiation_id)
            detail = (
                "no verified payment exists to refund"
                if isinstance(outcome, NotPaid)
                else "nothing left to reverse"
            )
            raise PaymentSettlementError(409, detail)
        if isinstance(outcome, RefundBlocked):
            logger.error("refund for %s needs operator action: %s", negotiation_id, outcome.reason)
            raise PaymentSettlementError(500, "payments integration needs operator action")
        if not isinstance(outcome, Refunded):
            raise PaymentSettlementError(503, "payments service is unavailable")
        await self.db.complete_vm_refund(negotiation_id=negotiation_id)

    @staticmethod
    def _refund_payload(negotiation_id: str, data: PaymentSettlementData) -> dict[str, Any]:
        return {
            "negotiation_id": negotiation_id,
            "settlement_ref": data.transaction_id,
            "status": "refunded",
        }

    async def _provision(
        self,
        negotiation_id: str,
        agreement: dict,
        binding: Any,
        evidence: Any,
    ) -> None:
        owner = self.owner
        delivery = self.db
        entry = self._entry(agreement)
        start = datetime.fromisoformat(agreement["start_utc"].replace("Z", "+00:00"))
        until = max(start, datetime.now(timezone.utc)) + timedelta(
            seconds=float(config.settings.provisioning.timeout) + 60
        )
        claimed = await delivery.claim_vm_delivery(
            negotiation_id=negotiation_id, owner=owner, lease_until=until.isoformat()
        )
        if not claimed:
            return
        try:
            row = await delivery.load_vm_delivery(negotiation_id=negotiation_id)
            if row.get("fulfillment_context"):
                # Resume the durable request instead of allocating a second VM.
                await delivery.release_vm_delivery(
                    negotiation_id=negotiation_id, owner=owner
                )
                await resume_incomplete_fulfillments_once(sqlite_client=self.db)
                return
            result = await fulfill_domain(
                self.domain,
                StorefrontFulfillmentContext(
                    thread_binding=binding,
                    settlement_evidence=evidence,
                    buyer_principal=Identity.model_validate(agreement["buyer"]),
                    ports=StorefrontFulfillmentPorts(
                        repository=delivery,
                        capacity_client=None,
                        fulfillment_client=None,
                    ),
                    domain_input={
                        "failure_policy": partial(
                            entry.delivery_failed, evidence=evidence, db=delivery
                        )
                    },
                ),
            )
            private = dict(result.domain_result or {})
            if result.state == "deferred":
                # The VM exists and a step after it is pending; the delivery
                # stays open for the fulfillment resume pass.
                return
            fulfillment_uid = None
            if result.state == "fulfilled":
                if result.fulfillment_id:
                    await delivery.update_vm_delivery(
                        negotiation_id=negotiation_id,
                        fulfillment_id=result.fulfillment_id,
                    )
                row = await delivery.load_vm_delivery(negotiation_id=negotiation_id)
                fulfillment_uid = await entry.continue_delivery(
                    evidence=evidence,
                    db=delivery,
                    delivery=row,
                    connection_json=private.get("connection_details"),
                )
            # A refund recorded after delivery started lives on the evidence;
            # the delivery's own outcome is still recorded here beside it.
            await delivery.update_vm_delivery(
                negotiation_id=negotiation_id,
                status="ready" if result.state == "fulfilled" else "failed",
                fulfillment_uid=fulfillment_uid,
                connection_details=private.get("connection_details"),
                tenant_credentials=json.dumps(private["tenant_credentials"])
                if private.get("tenant_credentials") is not None
                else None,
                reason=result.failure_reason,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "VM payment provisioning interrupted for %s", negotiation_id
            )
        finally:
            await delivery.release_vm_delivery(
                negotiation_id=negotiation_id, owner=owner
            )
