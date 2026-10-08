"""Receipt-gated VM provisioning, negotiation-scoped retry, and seller refunds.

Delivery start and refund intent are durable transitions on the deal's escrow
row, each one serialized write, so exactly one decides whether delivery
precedes a refund. A refund that wins stops delivery from starting; a delivery
that wins completes and is recorded beside the refund. The per-negotiation lock
only keeps one process's settlement and refund calls from interleaving.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    fulfill_domain,
)
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
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
    SignedReceipt,
    reconcile_accepted_payments,
)
from market_identity import Identity

from market_storefront.services.fulfillment_resume_runtime import (
    resume_incomplete_fulfillments_once,
)
from market_storefront.utils import config

logger = logging.getLogger(__name__)

_TERMINAL = ("ready", "failed", "refunded")


class PaymentSettlementError(RuntimeError):
    """A settlement or refund refusal carrying the HTTP status the route returns."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class PaymentSettleResult:
    """A settle or refund outcome: its status code and neutral payload fields."""

    status_code: int
    payload: dict[str, Any] = field(default_factory=dict)


class VmPaymentsCoordinator:
    def __init__(self, *, domain: Any, db: Any, stage: PaymentSellerStage) -> None:
        self.domain = domain
        self.db = db
        self.stage = stage
        self.tasks: dict[str, asyncio.Task] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    def _lock(self, negotiation_id: str) -> asyncio.Lock:
        return self.locks.setdefault(negotiation_id, asyncio.Lock())

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

    async def start(self, negotiation_id: str, thread: dict[str, Any]) -> PaymentSettleResult:
        async with self._lock(negotiation_id):
            raw, agreement, data = self._accepted(negotiation_id, thread)
            existing = await self.db.load_escrow(escrow_uid=negotiation_id)
            if existing and existing["negotiation_id"] != negotiation_id:
                raise PaymentSettlementError(409, "settlement coordinate belongs to another negotiation")
            if existing and existing["status"] in ("refunding", "refunded"):
                if existing["status"] == "refunding":
                    await self._complete_refund(negotiation_id, agreement, data)
                row = await self.db.load_escrow(escrow_uid=negotiation_id)
                return PaymentSettleResult(
                    200, self._neutral(negotiation_id, data, "refunded", row=row)
                )
            digest = hashlib.sha256(raw).hexdigest()
            record = await self.db.load_vm_payment_record(negotiation_id=negotiation_id)
            if record is not None and record["receipt"] is not None:
                receipt = SignedReceipt.model_validate(record["receipt"])
                if (
                    record["agreement_sha256"] != digest
                    or record["transaction_id"] != data.transaction_id
                    or not self.stage.receipt_matches(receipt, agreement, data)
                ):
                    logger.error("stored payment receipt for %s no longer verifies", negotiation_id)
                    raise PaymentSettlementError(409, "stored payment receipt does not prove this Agreement")
            else:
                outcome = await self.stage.check_receipt(agreement, data)
                if isinstance(outcome, ReceiptPending):
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
                await self.db.verify_vm_payment_record(
                    negotiation_id=negotiation_id,
                    agreement_sha256=digest,
                    transaction_id=data.transaction_id,
                    receipt=outcome.receipt.model_dump(mode="json", by_alias=True, exclude_none=True),
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
            if existing and existing["status"] in _TERMINAL:
                return PaymentSettleResult(
                    200, self._neutral(negotiation_id, data, existing["status"], row=existing)
                )
            await self.db.insert_escrow(
                escrow_uid=negotiation_id,
                negotiation_id=negotiation_id,
                chain_name=None,
                escrow_address=None,
                is_primary=True,
                status="provisioning",
            )
            task = self.tasks.get(negotiation_id)
            if task is None or task.done():
                provision = normalize_vm_provision_terms(agreement.get("provision_terms"))
                self.tasks[negotiation_id] = asyncio.create_task(
                    self._provision(negotiation_id, agreement, binding, provision)
                )
            row = await self.db.load_escrow(escrow_uid=negotiation_id)
            return PaymentSettleResult(
                202, self._neutral(negotiation_id, data, row["status"], row=row)
            )

    async def reconcile_once(self, *, limit: int = 100) -> ReconciliationPass:
        """Advance accepted payment deals a buyer has not settled, without the buyer.

        A deal with a recorded receipt and delivery belongs to the fulfillment
        resume sweep; this pass takes the deals before that point (no receipt
        recorded yet) and refunds left `refunding`.
        """
        candidates = await self.db.list_unsettled_payment_negotiations(
            mechanism=ARKHAI_PAYMENTS_MECHANISM, limit=limit
        )

        async def settle(negotiation_id: str) -> None:
            thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            await self.start(negotiation_id, thread)

        return await reconcile_accepted_payments(candidates, settle, logger=logger)

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
        return {
            "action": "refund",
            "status": "refunded" if status == "refunded" else "skipped",
            "escrow_kind": ARKHAI_PAYMENTS_MECHANISM,
            "settlement_ref": result.payload.get("settlement_ref"),
        }

    async def _refund_locked(
        self, negotiation_id: str, thread: dict[str, Any], *, require_undelivered: bool
    ) -> PaymentSettleResult:
        _, agreement, data = self._accepted(negotiation_id, thread)
        existing = await self.db.load_escrow(escrow_uid=negotiation_id)
        if existing and existing["status"] == "refunded":
            return PaymentSettleResult(200, self._refund_payload(negotiation_id, data))
        if require_undelivered and existing and existing["status"] == "ready":
            return PaymentSettleResult(200, self._neutral(negotiation_id, data, "ready"))
        if not existing or existing["status"] != "refunding":
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
        await self._complete_refund(negotiation_id, agreement, data)
        return PaymentSettleResult(200, self._refund_payload(negotiation_id, data))

    async def _complete_refund(
        self, negotiation_id: str, agreement: dict[str, Any], data: PaymentSettlementData
    ) -> None:
        """Record intent, reverse, then record the refund; safe to repeat after a crash."""

        intent = await self.db.record_refund_intent(
            escrow_uid=negotiation_id, negotiation_id=negotiation_id
        )
        if intent["status"] == "refunded":
            return
        outcome = await self.stage.reverse(agreement, data)
        if isinstance(outcome, (NotPaid, NothingToReverse)):
            await self.db.abandon_refund_intent(
                escrow_uid=negotiation_id, prior_status=intent["status"]
            )
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
        await self.db.update_escrow(escrow_uid=negotiation_id, status="refunded")

    @staticmethod
    def _refund_payload(negotiation_id: str, data: PaymentSettlementData) -> dict[str, Any]:
        return {
            "negotiation_id": negotiation_id,
            "settlement_ref": data.transaction_id,
            "status": "refunded",
        }

    async def _provision(
        self, negotiation_id: str, agreement: dict, binding: Any, provision: Any
    ) -> None:
        owner = f"payments:{negotiation_id}"
        start = datetime.fromisoformat(agreement["start_utc"].replace("Z", "+00:00"))
        until = max(start, datetime.now(timezone.utc)) + timedelta(
            seconds=float(config.settings.provisioning.timeout) + 60
        )
        claimed = await self.db.claim_escrow_convergence(
            escrow_uid=negotiation_id, owner=owner, lease_until=until.isoformat()
        )
        if not claimed:
            return
        try:
            row = await self.db.load_escrow(escrow_uid=negotiation_id)
            if row.get("fulfillment_phase") is None and not await self.db.claim_delivery_start(
                escrow_uid=negotiation_id
            ):
                # Refund intent was recorded first; delivery must not start.
                return
            if row.get("fulfillment_context"):
                # Resume the durable request instead of allocating a second VM.
                await self.db.release_escrow_convergence(
                    escrow_uid=negotiation_id, owner=owner
                )
                await resume_incomplete_fulfillments_once(sqlite_client=self.db)
                return
            listing = await self.db.load_listing(listing_id=agreement["listing_id"])
            if listing is None:
                raise ValueError("accepted listing is unavailable")
            result = await fulfill_domain(
                self.domain,
                StorefrontFulfillmentContext(
                    thread_binding=binding,
                    escrow_uid=negotiation_id,
                    buyer_principal=Identity.model_validate(agreement["buyer"]),
                    ports=StorefrontFulfillmentPorts(
                        repository=self.db,
                        capacity_client=None,
                        fulfillment_client=None,
                    ),
                    domain_input={
                        "ssh_public_key": provision.ssh_public_key,
                        "order": dict(listing),
                        "duration_seconds": agreement["duration_seconds"],
                        "start_utc": agreement["start_utc"],
                        "listing_id": agreement["listing_id"],
                        "settlement_mechanism": ARKHAI_PAYMENTS_MECHANISM,
                    },
                ),
            )
            private = dict(result.domain_result or {})
            async with self._lock(negotiation_id):
                current = await self.db.load_escrow(escrow_uid=negotiation_id)
                # A refund recorded after delivery started keeps its status; the
                # delivery's outcome is still recorded beside it.
                refunded = current is not None and current["status"] in ("refunding", "refunded")
                await self.db.update_escrow(
                    escrow_uid=negotiation_id,
                    status=None if refunded else ("ready" if result.state == "fulfilled" else "failed"),
                    fulfillment_uid=result.fulfillment_id,
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
            await self.db.release_escrow_convergence(
                escrow_uid=negotiation_id, owner=owner
            )
