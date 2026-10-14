"""Payment-only purchase stages for the bare-metal buyer."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import PaymentApproval, create_arkhai_payments_registration


def _agreement_bytes(outcome: Any) -> bytes:
    if (
        outcome.agreement is None
        or outcome.settlement_data is None
        or not outcome.agreement_bytes
    ):
        raise ValueError("accepted payment negotiation omitted its Agreement or mandate")
    return base64.b64decode(outcome.agreement_bytes, validate=True)


@dataclass(frozen=True, slots=True)
class PaymentStage:
    registration_factory = staticmethod(create_arkhai_payments_registration)

    @staticmethod
    def validate_option(option: Any) -> None:
        if len(option.rates) != 1:
            raise ValueError("buy requires one priced payment option")
        if option.rates[0].per != "hour":
            raise ValueError("bare-metal purchase currently requires an hourly option")

    @staticmethod
    def validate_acceptance(outcome: Any, approval: PaymentApproval) -> None:
        approval.check(_agreement_bytes(outcome), outcome.settlement_data)

    def settle(
        self,
        *,
        outcome: Any,
        approval: PaymentApproval,
        transport: Any,
        timeout: float,
        run_log: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Approve the mandate, then settle until the seller starts delivery.

        The seller verifies the receipt and starts fulfillment in the same settle
        call, so the buyer only retries while the seller reports no payment
        evidence yet. Returns the transaction ID and the seller's settle response.
        """

        transaction = approval.approve(
            _agreement_bytes(outcome),
            outcome.settlement_data,
            timeout=timeout,
        )
        run_log.event("payment_approved", transaction_id=transaction)
        deadline = time.monotonic() + timeout
        while True:
            settled = transport.settle(outcome.negotiation_id)
            if settled.get("status") != "pending":
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "seller has not observed the verified payment receipt"
                )
            time.sleep(min(1.0, remaining))
        if settled.get("settlement_ref") != transaction:
            raise RuntimeError("seller settled a different payment transaction")
        return transaction, settled
