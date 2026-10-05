"""Payment-only purchase stages for the bare-metal buyer."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import create_arkhai_payments_registration

from .arkhai_payments import BareMetalArkhaiPaymentsBuyer


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
    def validate_acceptance(outcome: Any, buyer: BareMetalArkhaiPaymentsBuyer) -> None:
        if (
            outcome.agreement is None
            or outcome.settlement_data is None
            or not outcome.agreement_bytes
        ):
            raise ValueError(
                "accepted payment negotiation omitted its Agreement or mandate"
            )
        buyer.validate_acceptance(
            agreement=outcome.agreement,
            settlement_data=outcome.settlement_data,
        )

    def settle(
        self,
        *,
        outcome: Any,
        buyer: BareMetalArkhaiPaymentsBuyer,
        transport: Any,
        timeout: float,
        run_log: Any,
    ) -> str:
        self.validate_acceptance(outcome, buyer)
        transaction = buyer.approve(
            agreement=outcome.agreement,
            settlement_data=outcome.settlement_data,
            timeout=timeout,
        )
        run_log.event("payment_approved", transaction_id=transaction)
        deadline = time.monotonic() + timeout
        while True:
            settled = transport.settle(outcome.negotiation_id)
            if settled.get("status") == "settlement_verified":
                if settled.get("escrow_uid") != transaction:
                    raise RuntimeError(
                        "seller verified a different payment transaction"
                    )
                return transaction
            if settled.get("status") != "settlement_pending":
                raise RuntimeError("seller returned an unexpected settlement status")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "seller has not observed the verified payment receipt"
                )
            time.sleep(min(1.0, remaining))
