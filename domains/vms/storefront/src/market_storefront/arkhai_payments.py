"""VM seller stage for Arkhai Agreement settlement."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    Mandate,
    MandatePolicy,
    PaymentsClient,
    PaymentsOptionParams,
    PaymentsPollTimeout,
    SignedReceipt,
    derive_mandate,
    payments_client_for_owner,
    transaction_id,
    verify_receipt,
)
from market_arkhai_payments.models import AccountId


@dataclass(frozen=True, slots=True)
class VmArkhaiPaymentsStage:
    """Derive accepted mandates and verify service receipts for VM deals."""

    config: ArkhaiPaymentsConfig

    @staticmethod
    def _option_for_agreement(agreement: Mapping[str, Any]) -> PaymentsOptionParams:
        selected = agreement.get("settlement")
        if (
            not isinstance(selected, Mapping)
            or selected.get("mechanism") != ARKHAI_PAYMENTS_MECHANISM
        ):
            raise ValueError("Agreement does not select Arkhai payments")
        return PaymentsOptionParams.model_validate(selected.get("params"))

    def _client(self, owner_account: str) -> PaymentsClient:
        return payments_client_for_owner(self.config, owner_account)

    def mandate_for_agreement(self, agreement: Mapping[str, Any]) -> dict[str, Any]:
        option = self._option_for_agreement(agreement)
        settlement_params = agreement.get("settlement_params")
        payer = (
            settlement_params.get("payer_account")
            if isinstance(settlement_params, Mapping)
            else None
        )
        payer_account = AccountId.model_validate(payer).root
        if self.config.fee_bps is None:
            raise ValueError("payments fee policy is not configured")
        if self.config.dispute_authority is None:
            raise ValueError("payments dispute authority is not configured")
        policy = MandatePolicy(
            buyer_account=payer_account,
            option=option,
            accepted_at=agreement["accepted_at"],
            start_utc=agreement["start_utc"],
            duration_seconds=agreement["duration_seconds"],
            amount=agreement["amount"],
            asset=agreement["asset"],
            fee_bps=self.config.fee_bps,
            dispute_authority=self.config.dispute_authority,
        )
        return derive_mandate(dict(agreement), policy).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )

    def receipt_matches(
        self,
        signed_receipt: Any,
        *,
        agreement: Mapping[str, Any],
        mandate: Mandate,
    ) -> bool:
        if self.config.service_identity is None:
            return False
        return verify_receipt(
            signed_receipt,
            self.config.service_identity,
            mandate=mandate,
            agreement_json=dict(agreement),
        )

    async def verify_receipt(
        self,
        *,
        transaction: str,
        agreement: Mapping[str, Any],
    ) -> SignedReceipt | None:
        """Poll for and verify the service receipt for the accepted Agreement."""
        mandate = Mandate.model_validate(self.mandate_for_agreement(agreement))
        expected_transaction = transaction_id(mandate)
        if transaction != expected_transaction:
            raise ValueError(
                "transaction ID does not match the accepted payment mandate"
            )
        if self.config.service_identity is None:
            raise ValueError("payments service identity is not configured")
        option = self._option_for_agreement(agreement)

        def verify_current_receipt() -> SignedReceipt | None:
            with self._client(option.payee_account) as client:
                try:
                    snapshot = client.poll(
                        expected_transaction, timeout=1.0, interval=0.25
                    )
                except PaymentsPollTimeout:
                    return None
                signed_receipt = snapshot.snapshot.receipt
                if not self.receipt_matches(
                    signed_receipt, agreement=agreement, mandate=mandate
                ):
                    raise ValueError(
                        "payments receipt does not match the accepted Agreement"
                    )
                if option.deposit_agreement:
                    client.ensure_agreement_attached(
                        expected_transaction, dict(agreement), option
                    )
                return signed_receipt

        return await asyncio.to_thread(verify_current_receipt)
