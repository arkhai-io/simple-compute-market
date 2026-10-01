"""Errors raised by the Arkhai payments client and mandate checks."""

from __future__ import annotations


class PaymentsError(Exception):
    """Base class for errors safe to handle at a payments boundary."""


class MandatePolicyError(PaymentsError, ValueError):
    """The proposed mandate does not satisfy the accepted payment policy."""


class PaymentsAPIError(PaymentsError):
    """An HTTP error returned by the payments service."""

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"payments service returned {status_code}: {code}")


class PaymentsTransportError(PaymentsError):
    """The service could not be reached or its response could not be read."""


class PaymentsProtocolError(PaymentsError):
    """The service response did not match the published wire contract."""


class PaymentsPollTimeout(PaymentsError, TimeoutError):
    """No transaction appeared before the requested polling deadline."""

    def __init__(self, transaction: str) -> None:
        self.transaction = transaction
        super().__init__(f"timed out waiting for transaction {transaction}")
