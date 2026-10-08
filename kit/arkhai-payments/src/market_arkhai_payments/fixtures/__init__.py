"""Test fixtures for consumers of the Arkhai payments kit.

The receipt fixture shares the kit verifier's framing and is proven against the
published conformance vector, so tests never sign receipts any other way.
"""

from market_arkhai_payments.fixtures.payments_client import FakePaymentsClient
from market_arkhai_payments.fixtures.receipts import (
    build_signed_receipt,
    receipt_parts,
    sign_receipt,
)

__all__ = ["FakePaymentsClient", "build_signed_receipt", "receipt_parts", "sign_receipt"]
