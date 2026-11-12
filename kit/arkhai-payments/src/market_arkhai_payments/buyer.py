"""Buyer-side approval of a seller-derived mandate.

The buyer re-derives the mandate from the exact accepted Agreement bytes under its
own trusted policy and approves only an identical one. It never deposits the
Agreement on the seller's behalf; attachment at approval is the buyer's own policy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from market_core.schemas import Agreement, SettlementOption
from market_deal_lifecycle.terms import TermContext
from market_settlement_runtime.buyer_terms import BuyerTermsPolicy
from market_settlement_runtime.rate_publication import default_buyer_refusals
from pydantic import ValidationError

from market_arkhai_payments.agreement import (
    PaymentSettlementData,
    agreement_from_bytes,
    mandate_policy_for_agreement,
    selected_payment_option,
)
from market_arkhai_payments.errors import (
    MandatePolicyError,
    PaymentApprovalDeclined,
    ReceiptVerificationError,
)
from market_arkhai_payments.mandates import SUPPORTED_PARTIAL_PERIODS, check
from market_arkhai_payments.models import AccountId, Mandate
from market_arkhai_payments.receipts import verify_receipt, verify_snapshot
from market_arkhai_payments.seller import ClientForOwner
from market_arkhai_payments.settlement_config import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    ArkhaiPaymentsConfigurationError,
    payments_client_for_owner,
)

ConfirmPayment = Callable[[Mandate, str], bool]


def approvable_terms(context: TermContext) -> TermContext:
    """A buyer's payments term context, with the terms this helper can take.

    It approves a rate part that a stop ends, each mandate encoding the stop
    entries and term end its Agreement's partial-period treatments name, so a
    buyer selects exactly the options whose mandate it can re-derive and approve.
    """
    if context.mechanism != ARKHAI_PAYMENTS_MECHANISM:
        raise ValueError(f"{context.mechanism} is not {ARKHAI_PAYMENTS_MECHANISM}")
    return replace(
        context, has_stoppable_part=True, supported_partial_periods=SUPPORTED_PARTIAL_PERIODS,
    )


class PaymentApproval:
    """Approve accepted payment mandates from one buyer Arkhai account."""

    def __init__(
        self,
        config: ArkhaiPaymentsConfig,
        payer_account: str,
        *,
        client_for_owner: ClientForOwner | None = None,
        terms_policy: BuyerTermsPolicy | None = None,
    ) -> None:
        if (
            config.fee_bps is None
            or config.service_identity is None
        ):
            raise ArkhaiPaymentsConfigurationError(
                "payments fee policy and service identity are required"
            )
        self.config = config
        self.terms_policy = terms_policy
        self.payer_account = AccountId.model_validate(payer_account).root
        self._client_for_owner: ClientForOwner = client_for_owner or (
            lambda owner: payments_client_for_owner(config, owner)
        )

    def check(
        self,
        agreement_bytes: bytes | str,
        settlement_data: Any,
    ) -> tuple[dict[str, Any], PaymentSettlementData]:
        """Validate the seller's artifacts against the Agreement and this buyer's policy.

        That the Agreement selected the advertised option is established when the
        buyer accepts the negotiation, for every mechanism; this checks only the
        payment-specific facts.
        """

        agreement = agreement_from_bytes(agreement_bytes)
        try:
            Agreement.model_validate(agreement)
        except ValidationError as exc:
            raise MandatePolicyError("accepted Agreement is malformed") from exc
        selected_payment_option(agreement)
        data = PaymentSettlementData.parse(settlement_data)
        policy = mandate_policy_for_agreement(
            agreement, self.config, expected_payer=self.payer_account
        )
        check(data.mandate, agreement, policy)
        if policy.option.period is not None:
            if self.terms_policy is not None:
                self.terms_policy.rank(SettlementOption.model_validate(agreement["settlement"]))
            else:
                refusals = default_buyer_refusals(policy.lifecycle, has_adapter=True)
                if refusals:
                    raise MandatePolicyError("; ".join(refusals))
        return agreement, data

    def approve(
        self,
        agreement_bytes: bytes | str,
        settlement_data: Any,
        *,
        confirm: ConfirmPayment | None = None,
        timeout: float = 300.0,
        interval: float = 1.0,
    ) -> str:
        """Approve an identical mandate, then wait for its verified receipt; return its ID."""

        agreement, data = self.check(agreement_bytes, settlement_data)
        if confirm is not None and not confirm(data.mandate, data.transaction_id):
            raise PaymentApprovalDeclined("buyer declined payment approval")
        assert self.config.service_identity is not None
        attachment = agreement if self.config.attach_agreement else None
        with self._client_for_owner(self.payer_account) as client:
            approved = client.approve(data.mandate, agreement=attachment)
            self._require_proof(approved, agreement, data, "approval")
            snapshot = client.poll(data.transaction_id, timeout=timeout, interval=interval)
        if not verify_snapshot(
            snapshot, self.config.receipt_trust, mandate=data.mandate,
            agreement_json=agreement, livemode=self.config.livemode,
        ):
            raise ReceiptVerificationError("payments transaction receipt/snapshot does not prove the accepted Agreement")
        return data.transaction_id

    def _require_proof(
        self,
        receipt: Any,
        agreement: Mapping[str, Any],
        data: PaymentSettlementData,
        label: str,
    ) -> None:
        assert self.config.service_identity is not None
        if not verify_receipt(
            receipt,
            self.config.receipt_trust,
            mandate=data.mandate,
            agreement_json=dict(agreement),
            livemode=self.config.livemode,
        ):
            raise ReceiptVerificationError(
                f"payments {label} receipt does not prove the accepted Agreement"
            )


__all__ = ["ConfirmPayment", "PaymentApproval"]
