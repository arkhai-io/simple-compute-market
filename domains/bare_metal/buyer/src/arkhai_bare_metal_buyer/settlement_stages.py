"""Payment-only purchase stages for the bare-metal buyer."""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import PaymentApproval, create_arkhai_payments_registration
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage, Pending

from .evidence import evidence_store
from .lifecycle import buyer_lifecycle, run_sync


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
        if len(option.price_rates) != 1:
            raise ValueError("buy requires one priced payment option")
        if option.price_rates[0].per != "hour":
            raise ValueError("bare-metal purchase currently requires an hourly option")

    @staticmethod
    def validate_acceptance(outcome: Any, approval: PaymentApproval) -> None:
        approval.check(_agreement_bytes(outcome), outcome.settlement_data)

    def settle(
        self,
        *,
        outcome: Any,
        approval: PaymentApproval,
        seller_url: str,
        signer: Any,
        publishers: Any,
        config: Any,
        timeout: float,
        run_log: Any,
    ) -> tuple[str, dict[str, Any]]:
        """Approve the exact mandate, then commit through the buyer half."""
        transaction = approval.approve(
            _agreement_bytes(outcome), outcome.settlement_data, timeout=timeout,
        )
        evidence_store().remember_commitment(outcome.negotiation_id, transaction)
        run_log.event("payment_approved", transaction_id=transaction)

        async def commit():
            async with buyer_lifecycle(
                agreement_bytes=_agreement_bytes(outcome), settlement_data=outcome.settlement_data,
                seller_url=seller_url, signer=signer, publishers=publishers,
                config=config, approval=approval,
            ) as lifecycle:
                deadline = time.monotonic() + timeout
                message = CommitMessage(
                    negotiation_id=outcome.negotiation_id, commitment_ref=transaction,
                    operation_key="commit:" + transaction,
                )
                while True:
                    result = await lifecycle.commit(message)
                    if isinstance(result, Accepted):
                        return
                    if not isinstance(result, Pending):
                        raise RuntimeError("seller commit: " + result.model_dump_json())
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("seller has not observed the verified payment receipt")
                    await asyncio.sleep(min(1.0, remaining))

        run_sync(commit)
        # Delivery remains the domain's projection, not a payment acknowledgement.
        return transaction, {"status": "committed", "settlement_ref": transaction,
                             "negotiation_id": outcome.negotiation_id}
