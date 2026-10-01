"""Stateless client for the external Arkhai payments authority."""

from market_arkhai_payments.client import PaymentsClient
from market_arkhai_payments.errors import (
    MandatePolicyError,
    PaymentsAPIError,
    PaymentsError,
    PaymentsPollTimeout,
    PaymentsProtocolError,
    PaymentsTransportError,
)
from market_arkhai_payments.mandates import (
    MandatePolicy,
    PaymentsOptionParams,
    check,
    derive_mandate,
    duration_seconds,
    format_duration,
)
from market_arkhai_payments.receipts import agreement_hash, transaction_id, verify_receipt
from market_arkhai_payments.models import (
    ApiError,
    ApprovalRequest,
    DealAttachment,
    Mandate,
    SignedReceipt,
    SignedTransactionSnapshot,
    StoredDealAttachment,
    StoredEvent,
)

__all__ = [
    "ApiError",
    "ApprovalRequest",
    "DealAttachment",
    "Mandate",
    "MandatePolicy",
    "MandatePolicyError",
    "PaymentsAPIError",
    "PaymentsClient",
    "PaymentsError",
    "PaymentsOptionParams",
    "PaymentsPollTimeout",
    "PaymentsProtocolError",
    "PaymentsTransportError",
    "SignedReceipt",
    "SignedTransactionSnapshot",
    "StoredDealAttachment",
    "StoredEvent",
    "agreement_hash",
    "check",
    "derive_mandate",
    "duration_seconds",
    "format_duration",
    "transaction_id",
    "verify_receipt",
]
