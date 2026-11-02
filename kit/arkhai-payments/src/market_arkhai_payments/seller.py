"""Seller-side payment settlement: acceptance data, receipt checks, deposit, reversal.

A storefront maps these outcomes to its own responses; nothing here knows HTTP. The
seller never polls inside a request: each check is one read of the transaction, and
the buyer's settlement retries are the polling loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand, Pending, Rejected, Unknown

from market_arkhai_payments.adapter import PaymentAdapter
from market_arkhai_payments.agreement import (
    PaymentSettlementData,
    agreement_from_bytes,
    selected_payment_option,
)
from market_arkhai_payments.client import PaymentsClient
from market_arkhai_payments.errors import (
    PaymentsAPIError,
    PaymentsBlocked,
    PaymentsError,
    PaymentsTransportError,
    PaymentsUnavailable,
)
from market_arkhai_payments.models import SignedReceipt, StoredEvent
from market_arkhai_payments.receipts import SnapshotVerifier, verify_receipt, verify_snapshot
from market_arkhai_payments.settlement_config import (
    ArkhaiPaymentsConfig,
    ArkhaiPaymentsConfigurationError,
    payments_client_for_owner,
)

ClientForOwner = Callable[[str], PaymentsClient]

# Service codes meaning the transaction exists but no held funds remain to reverse.
_NOTHING_TO_REVERSE = frozenset({"hold_matured", "hold_not_reversible", "insufficient_held_funds"})
# Service codes for failures a retry may clear.
_TRANSIENT_CODES = frozenset({"ledger_unavailable", "account_directory_unavailable", "internal_error"})


def _transient(exc: Exception) -> bool:
    """Whether a failed payments call may succeed if simply retried.

    Transport failures, rate limiting, server errors, and the service's own
    availability codes are transient. Authentication, authorization, missing
    configuration, and responses outside the published contract are not.
    """

    if isinstance(exc, PaymentsTransportError):
        return True
    if isinstance(exc, PaymentsAPIError):
        return (
            exc.status_code == 429
            or exc.status_code >= 500
            or exc.code in _TRANSIENT_CODES
        )
    return False


def _reason(exc: Exception) -> str:
    if isinstance(exc, PaymentsAPIError):
        return f"payments service returned {exc.code}"
    return str(exc)


@dataclass(frozen=True, slots=True)
class ReceiptPending:
    """The service has no transaction for the mandate yet; retrying may verify it."""

    transaction_id: str


@dataclass(frozen=True, slots=True)
class ReceiptVerified:
    """A service-signed receipt proves the exact Agreement and mandate."""

    transaction_id: str
    receipt: SignedReceipt


@dataclass(frozen=True, slots=True)
class ReceiptInvalid:
    """A receipt exists but does not prove the Agreement.

    The buyer cannot cause this: the transaction ID hashes a mandate the seller
    derived. It indicates a stale trust pin, a service fault, or tampering, so a
    storefront records nothing and refuses without inviting a retry.
    """

    transaction_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReceiptUnavailable:
    """The service was unreachable or reported a transient failure; retrying may verify it."""

    transaction_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReceiptBlocked:
    """The check failed in a way only the seller's operator can repair."""

    transaction_id: str
    reason: str


ReceiptOutcome = (
    ReceiptPending | ReceiptVerified | ReceiptInvalid | ReceiptUnavailable | ReceiptBlocked
)


@dataclass(frozen=True, slots=True)
class Refunded:
    """Every held part is reversed; ``event`` is absent when an earlier call reversed it."""

    transaction_id: str
    event: StoredEvent | None


@dataclass(frozen=True, slots=True)
class NotPaid:
    """No verified payment exists to reverse."""

    transaction_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class NothingToReverse:
    """The payment exists but its hold has matured or was already reversed."""

    transaction_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class RefundUnavailable:
    """The reversal hit a transient failure; retrying may complete it."""

    transaction_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class RefundBlocked:
    """The reversal failed in a way only the seller's operator can repair."""

    transaction_id: str
    reason: str


RefundOutcome = Refunded | NotPaid | NothingToReverse | RefundUnavailable | RefundBlocked


class PaymentSellerStage:
    """One seller's payment settlement operations under its trusted policy.

    Construction needs only what servicing an accepted deal needs: the service
    URL and the pinned receipt identity. Deriving settlement data for a new
    acceptance additionally needs the fee policy and dispute authority, which
    publication readiness guarantees before any option is published.
    """

    def __init__(
        self,
        config: ArkhaiPaymentsConfig,
        *,
        client_for_owner: ClientForOwner | None = None,
        snapshot_verifier: Callable[[Mapping[str, Any], PaymentSettlementData], SnapshotVerifier] | None = None,
    ) -> None:
        if config.service_url is None or config.service_identity is None:
            raise ArkhaiPaymentsConfigurationError(
                "payments service URL and receipt identity are required for servicing"
            )
        self.config = config
        self._snapshot_verifier = snapshot_verifier or self._verifier_for
        self._client_for_owner: ClientForOwner = client_for_owner or (
            lambda owner: payments_client_for_owner(config, owner)
        )

    def _verifier_for(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData,
    ) -> SnapshotVerifier:
        return lambda signed, minimum_sequence: verify_snapshot(
            signed, self.config.receipt_trust, mandate=data.mandate,
            agreement_json=agreement, livemode=self.config.livemode,
            minimum_sequence=minimum_sequence,
        )

    def settlement_data(self, agreement: Mapping[str, Any]) -> PaymentSettlementData:
        """Derive the acceptance artifact returned to the buyer and stored with the thread."""

        return PaymentSettlementData.for_agreement(agreement, self.config)

    def accepted(
        self, agreement_bytes: bytes | str, stored: Any
    ) -> tuple[dict[str, Any], PaymentSettlementData]:
        """Decode stored acceptance state and require the Agreement to derive it exactly."""

        agreement = agreement_from_bytes(agreement_bytes)
        data = PaymentSettlementData.parse(stored)
        data.require_bound_to(agreement)
        return agreement, data

    def receipt_matches(
        self,
        receipt: SignedReceipt | Mapping[str, Any],
        agreement: Mapping[str, Any],
        data: PaymentSettlementData,
    ) -> bool:
        assert self.config.service_identity is not None
        return verify_receipt(
            receipt,
            self.config.receipt_trust,
            mandate=data.mandate,
            agreement_json=dict(agreement),
            livemode=self.config.livemode,
        )

    def check_receipt_now(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> ReceiptOutcome:
        txid = data.transaction_id
        try:
            owner = selected_payment_option(agreement).payee_account
            with self._client_for_owner(owner) as client:
                snapshot = client.get_transaction(txid)
        except PaymentsAPIError as exc:
            if exc.code == "transaction_not_found":
                return ReceiptPending(txid)
            if _transient(exc):
                return ReceiptUnavailable(txid, _reason(exc))
            return ReceiptBlocked(txid, _reason(exc))
        except (PaymentsError, ArkhaiPaymentsConfigurationError) as exc:
            if _transient(exc):
                return ReceiptUnavailable(txid, _reason(exc))
            return ReceiptBlocked(txid, _reason(exc))
        if snapshot.snapshot.transaction.root != txid:
            return ReceiptBlocked(txid, "payments service returned another transaction")
        assert self.config.service_identity is not None
        if not self._snapshot_verifier(agreement, data)(snapshot, 0):
            return ReceiptInvalid(txid, "payments snapshot does not prove the accepted Agreement")
        return ReceiptVerified(txid, snapshot.snapshot.receipt)

    async def check_receipt(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> ReceiptOutcome:
        return await asyncio.to_thread(self.check_receipt_now, agreement, data)

    def deposit_now(self, agreement: Mapping[str, Any], data: PaymentSettlementData) -> None:
        """Attach the Agreement when the selected option advertises deposit.

        Runs after the receipt is recorded and before any delivery effect, so a
        seller never delivers without honoring a term the buyer may have filtered on.
        """

        option = selected_payment_option(agreement)
        if not option.deposit_agreement:
            return
        try:
            with self._client_for_owner(option.payee_account) as client:
                client.ensure_agreement_attached(data.transaction_id, dict(agreement), option)
        except (PaymentsError, ArkhaiPaymentsConfigurationError) as exc:
            if _transient(exc):
                raise PaymentsUnavailable("payments Agreement deposit is unavailable") from exc
            raise PaymentsBlocked(f"payments Agreement deposit failed: {_reason(exc)}") from exc

    async def deposit_if_advertised(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> None:
        await asyncio.to_thread(self.deposit_now, agreement, data)

    def payment_adapter(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData, *, minimum_sequence: int = 0,
    ) -> PaymentAdapter:
        """Bind the payee's lifecycle port without taking ownership of its watch cursor."""

        return PaymentAdapter(
            agreement, data, account=selected_payment_option(agreement).payee_account,
            client_for_owner=self._client_for_owner,
            verify_snapshot=self._snapshot_verifier(agreement, data), minimum_sequence=minimum_sequence,
        )

    def reverse_now(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData,
    ) -> RefundOutcome:
        """Refund through voluntary per-part lifecycle reverses and verified reads.

        A lost answer leaves no local assertion that funds moved. The next call
        reads the authority, recovers the stable operation and finishes any
        remaining parts. Reconciliation uses the same accepted-deal path.
        """

        txid = data.transaction_id
        current = self.check_receipt_now(agreement, data)
        if isinstance(current, ReceiptPending):
            return NotPaid(txid, "no approved payment exists for this deal")
        if isinstance(current, ReceiptInvalid):
            return NotPaid(txid, current.reason)
        if isinstance(current, ReceiptUnavailable):
            return RefundUnavailable(txid, current.reason)
        if isinstance(current, ReceiptBlocked):
            return RefundBlocked(txid, current.reason)
        adapter = self.payment_adapter(agreement, data)
        try:
            before = adapter.snapshot_now().snapshot
            if all(part.status.value == "reversed" for part in before.parts):
                return Refunded(txid, None)
            event = None
            for part in before.parts:
                if int(part.held.root) == 0:
                    continue
                operation_key = f"refund-{txid}-{part.part}"
                keys = OperationKeys(adapter.negotiation_id, operation_key)
                request_id = keys.part_event(str(part.part), "reverse")
                prior = next((entry.root for entry in before.events
                              if isinstance(entry.root, StoredEvent)
                              and entry.root.account.root == adapter.account
                              and entry.root.requestId.root == request_id), None)
                amount = prior.event.amount.root if prior is not None and prior.event.amount else part.held.root
                command = LifecycleCommand(
                    negotiation_id=adapter.negotiation_id, kind="reverse", operation_key=operation_key,
                    payload={"part": str(part.part), "amount": amount},
                )
                outcome = adapter.submit_now(command, keys)
                if isinstance(outcome, Unknown):
                    return RefundUnavailable(txid, outcome.reason)
                if isinstance(outcome, Pending):
                    return NotPaid(txid, outcome.reason)
                if isinstance(outcome, Rejected):
                    if any(code in outcome.reason for code in _NOTHING_TO_REVERSE):
                        return NothingToReverse(txid, outcome.reason)
                    if any(code in outcome.reason for code in _TRANSIENT_CODES):
                        return RefundUnavailable(txid, outcome.reason)
                    return RefundBlocked(txid, outcome.reason)
                assert isinstance(outcome, Accepted)
                after = adapter.snapshot_now().snapshot
                event = next((entry.root for entry in after.events
                              if isinstance(entry.root, StoredEvent)
                              and entry.root.account.root == adapter.account
                              and entry.root.requestId.root == request_id), event)
            final = adapter.snapshot_now().snapshot
            if all(part.status.value == "reversed" for part in final.parts):
                return Refunded(txid, event)
            return NothingToReverse(txid, "not every payment part remains fully reversible")
        except (PaymentsError, ArkhaiPaymentsConfigurationError) as exc:
            if _transient(exc):
                return RefundUnavailable(txid, _reason(exc))
            return RefundBlocked(txid, _reason(exc))

    async def reverse(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> RefundOutcome:
        return await asyncio.to_thread(self.reverse_now, agreement, data)


def servicing_stage(
    section: Any, *, client_for_owner: ClientForOwner | None = None
) -> PaymentSellerStage | None:
    """The seller stage for servicing accepted deals, whether or not publishing is enabled.

    A payments section carrying the service URL and receipt identity yields a
    stage even when the mechanism is disabled for new deals, so accepted deals
    keep settling and refunding. Without those fields there is nothing to
    service with, and the caller reports accepted deals as needing an operator.
    """

    if section is None:
        return None
    config = ArkhaiPaymentsConfig.model_validate(
        section.model_dump() if hasattr(section, "model_dump") else section
    )
    if config.service_url is None or config.service_identity is None:
        return None
    return PaymentSellerStage(config, client_for_owner=client_for_owner)


__all__ = [
    "ClientForOwner",
    "NotPaid",
    "NothingToReverse",
    "PaymentSellerStage",
    "ReceiptBlocked",
    "ReceiptInvalid",
    "ReceiptOutcome",
    "ReceiptPending",
    "ReceiptUnavailable",
    "ReceiptVerified",
    "RefundBlocked",
    "RefundOutcome",
    "RefundUnavailable",
    "Refunded",
    "servicing_stage",
]
