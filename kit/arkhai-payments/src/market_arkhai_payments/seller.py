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

from market_arkhai_payments.agreement import (
    PaymentSettlementData,
    agreement_from_bytes,
    selected_payment_option,
)
from market_arkhai_payments.client import PaymentsClient
from market_arkhai_payments.errors import (
    PaymentsAPIError,
    PaymentsError,
    PaymentsUnavailable,
)
from market_arkhai_payments.models import SignedReceipt, StoredEvent
from market_arkhai_payments.receipts import verify_receipt
from market_arkhai_payments.settlement_config import (
    ArkhaiPaymentsConfig,
    ArkhaiPaymentsConfigurationError,
    payments_client_for_owner,
)

ClientForOwner = Callable[[str], PaymentsClient]

# Service codes meaning the transaction exists but no held funds remain to reverse.
_NOTHING_TO_REVERSE = frozenset({"hold_matured", "hold_not_reversible", "insufficient_held_funds"})


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
    """The service could not be reached or answered outside its published contract."""

    transaction_id: str
    reason: str


ReceiptOutcome = ReceiptPending | ReceiptVerified | ReceiptInvalid | ReceiptUnavailable


@dataclass(frozen=True, slots=True)
class Refunded:
    transaction_id: str
    event: StoredEvent


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
    transaction_id: str
    reason: str


RefundOutcome = Refunded | NotPaid | NothingToReverse | RefundUnavailable


class PaymentSellerStage:
    """One seller's payment settlement operations under its trusted policy.

    Construction requires the policy every operation needs, so a storefront with
    incomplete payment configuration fails at composition rather than per request.
    """

    def __init__(
        self,
        config: ArkhaiPaymentsConfig,
        *,
        client_for_owner: ClientForOwner | None = None,
    ) -> None:
        if (
            config.fee_bps is None
            or config.dispute_authority is None
            or config.service_identity is None
        ):
            raise ArkhaiPaymentsConfigurationError(
                "payments fee policy, dispute authority, and service identity are required"
            )
        self.config = config
        self._client_for_owner: ClientForOwner = client_for_owner or (
            lambda owner: payments_client_for_owner(config, owner)
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
        data.require_derived_from(agreement, self.config)
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
            self.config.service_identity,
            mandate=data.mandate,
            agreement_json=dict(agreement),
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
            return ReceiptUnavailable(txid, f"payments service returned {exc.code}")
        except (PaymentsError, ArkhaiPaymentsConfigurationError) as exc:
            return ReceiptUnavailable(txid, str(exc))
        if snapshot.snapshot.transaction.root != txid:
            return ReceiptUnavailable(txid, "payments service returned another transaction")
        receipt = snapshot.snapshot.receipt
        if not self.receipt_matches(receipt, agreement, data):
            return ReceiptInvalid(txid, "payments receipt does not prove the accepted Agreement")
        return ReceiptVerified(txid, receipt)

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
            raise PaymentsUnavailable("payments Agreement deposit is unavailable") from exc

    async def deposit_if_advertised(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> None:
        await asyncio.to_thread(self.deposit_now, agreement, data)

    def reverse_now(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> RefundOutcome:
        """Reverse every still-held part, after re-checking that a verified payment exists."""

        txid = data.transaction_id
        current = self.check_receipt_now(agreement, data)
        if isinstance(current, ReceiptPending):
            return NotPaid(txid, "no approved payment exists for this deal")
        if isinstance(current, ReceiptInvalid):
            return NotPaid(txid, current.reason)
        if isinstance(current, ReceiptUnavailable):
            return RefundUnavailable(txid, current.reason)
        try:
            owner = selected_payment_option(agreement).payee_account
            with self._client_for_owner(owner) as client:
                event = client.reverse(txid)
        except PaymentsAPIError as exc:
            if exc.code == "transaction_not_found":
                return NotPaid(txid, "no approved payment exists for this deal")
            if exc.code in _NOTHING_TO_REVERSE:
                return NothingToReverse(txid, f"payments service returned {exc.code}")
            return RefundUnavailable(txid, f"payments service returned {exc.code}")
        except (PaymentsError, ArkhaiPaymentsConfigurationError) as exc:
            return RefundUnavailable(txid, str(exc))
        return Refunded(txid, event)

    async def reverse(
        self, agreement: Mapping[str, Any], data: PaymentSettlementData
    ) -> RefundOutcome:
        return await asyncio.to_thread(self.reverse_now, agreement, data)


__all__ = [
    "ClientForOwner",
    "NotPaid",
    "NothingToReverse",
    "PaymentSellerStage",
    "ReceiptInvalid",
    "ReceiptOutcome",
    "ReceiptPending",
    "ReceiptUnavailable",
    "ReceiptVerified",
    "RefundOutcome",
    "RefundUnavailable",
    "Refunded",
]
