"""Payment-only purchase stages for the bare-metal buyer."""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import PaymentApproval, create_arkhai_payments_registration
from market_core.schemas import AgreedPrice, rate_scales_by_time
from market_settlement_runtime.buyer_terms import option_quote
from market_settlement_runtime import SettlementConfigurationRegistry
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


def _time_price(option: Any) -> Any:
    """The option's one ``amount`` rate, which must scale by time.

    A purchase pays only that rate, so an option charging on any other field, a
    deposit for instance, is refused rather than bought with that charge unpaid.
    """

    if any(rate.field != "amount" for rate in option.price_rates):
        raise ValueError("buy pays only an amount rate; the option charges another field")
    amount_rates = [rate for rate in option.price_rates if rate.field == "amount"]
    if len(amount_rates) != 1:
        raise ValueError("buy requires one priced payment option")
    if not rate_scales_by_time(amount_rates[0]):
        raise ValueError("bare-metal purchase requires a time-priced option")
    return amount_rates[0]


#: The lease ``bare-metal buy`` requests for a reserved option when the buyer
#: names none: v0.3.0 shipped this default, so its reserved scripts keep buying
#: an hour. A recurring option never takes it; its horizon is the seller's bound.
RESERVED_DEFAULT_DURATION_SECONDS = 3600


def requested_duration(
    option: Any, duration_seconds: int | None, *, registry: SettlementConfigurationRegistry,
) -> tuple[int | None, bool]:
    """The duration a purchase requests, and whether it is the reserved default.

    The option's installed mechanism says whether it bills once for the whole
    term; the buyer reads no payment field to decide it.
    """
    if duration_seconds is not None:
        return duration_seconds, False
    if registry.project_billing(option).unit == "total":
        return RESERVED_DEFAULT_DURATION_SECONDS, True
    return None, False


def purchase_quote(
    option: Any, duration_seconds: int | None, *, registry: SettlementConfigurationRegistry | None = None,
) -> int:
    """One whole-term or per-period quote, never scaled by a recurring horizon."""
    registry = registry or SettlementConfigurationRegistry((create_arkhai_payments_registration(),))
    quote = option_quote(option, duration_seconds, registry=registry)
    if quote.amount < 1:
        raise ValueError("quote is zero base units; request a longer term or period")
    return quote.amount


def require_quoted_agreement(
    outcome: Any, *, amount: int, duration_seconds: int | None,
    quote: AgreedPrice | None = None, registry: SettlementConfigurationRegistry | None = None,
) -> None:
    """Refuse accepted money/unit or an explicitly requested duration mismatch.

    The mandate is derived from the Agreement and checked against it, so this is where
    the buyer holds the Agreement to the quote it requested, before any approval.
    """

    agreement = outcome.agreement
    if agreement is None:
        raise ValueError("accepted payment negotiation omitted its Agreement")
    if duration_seconds is not None and agreement.duration_seconds != duration_seconds:
        raise ValueError(
            f"seller Agreement is for {agreement.duration_seconds} seconds, "
            f"not the {duration_seconds} requested"
        )
    registry = registry or SettlementConfigurationRegistry((create_arkhai_payments_registration(),))
    accepted = registry.agreed_price(agreement)
    if accepted.amount != amount or (quote is not None and accepted != quote) or (
        quote is None and accepted.unit != "total"
    ):
        raise ValueError(
            f"seller Agreement price {accepted.amount} ({accepted.unit}) differs from the quoted {amount} "
            f"{quote.unit if quote is not None else 'total'}"
        )


@dataclass(frozen=True, slots=True)
class PaymentStage:
    registration_factory = staticmethod(create_arkhai_payments_registration)

    @staticmethod
    def validate_option(option: Any) -> None:
        _time_price(option)

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
