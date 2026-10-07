"""Agreement-to-mandate policy and the settlement data returned at acceptance.

Every party derives the mandate from the exact accepted Agreement, so the seller's
acceptance artifact, the buyer's check, and the seller's later verification all
use these functions rather than reading Agreement fields themselves.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from market_arkhai_payments.errors import MandatePolicyError
from market_arkhai_payments.mandates import MandatePolicy, PaymentsOptionParams, derive_mandate
from market_arkhai_payments.models import AccountId, Mandate
from market_arkhai_payments.receipts import transaction_id
from market_arkhai_payments.settlement_config import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
)


def agreement_from_bytes(agreement_bytes: bytes | str) -> dict[str, Any]:
    """Decode exact accepted Agreement bytes into the object every hash commits to."""

    try:
        value = json.loads(agreement_bytes)
    except (TypeError, ValueError) as exc:
        raise MandatePolicyError("accepted Agreement bytes are not JSON") from exc
    if not isinstance(value, dict):
        raise MandatePolicyError("accepted Agreement must be a JSON object")
    return value


def selected_payment_option(agreement: Mapping[str, Any]) -> PaymentsOptionParams:
    """Return the payments option the Agreement selected, or refuse another mechanism."""

    selected = agreement.get("settlement")
    if not isinstance(selected, Mapping) or selected.get("mechanism") != ARKHAI_PAYMENTS_MECHANISM:
        raise MandatePolicyError(f"Agreement does not select {ARKHAI_PAYMENTS_MECHANISM}")
    try:
        return PaymentsOptionParams.model_validate(selected.get("params"))
    except ValidationError as exc:
        raise MandatePolicyError("selected payments option parameters are invalid") from exc


def agreement_payer_account(agreement: Mapping[str, Any]) -> str:
    """Return the buyer's Arkhai account carried in the Agreement's settlement params."""

    params = agreement.get("settlement_params")
    payer = params.get("payer_account") if isinstance(params, Mapping) else None
    try:
        return AccountId.model_validate(payer).root
    except ValidationError as exc:
        raise MandatePolicyError("Agreement does not name a valid payer account") from exc


def mandate_policy_for_agreement(
    agreement: Mapping[str, Any],
    config: ArkhaiPaymentsConfig,
    *,
    expected_payer: str | None = None,
) -> MandatePolicy:
    """Build the exact mandate policy an accepted Agreement and trusted policy imply."""

    if config.fee_bps is None or config.dispute_authority is None:
        raise MandatePolicyError("payments fee policy and dispute authority are required")
    payer = agreement_payer_account(agreement)
    if expected_payer is not None and payer != expected_payer:
        raise MandatePolicyError("Agreement names a different payer account")
    try:
        return MandatePolicy(
            buyer_account=payer,
            option=selected_payment_option(agreement),
            accepted_at=agreement["accepted_at"],
            start_utc=agreement["start_utc"],
            duration_seconds=agreement["duration_seconds"],
            amount=agreement["amount"],
            asset=agreement["asset"],
            fee_bps=config.fee_bps,
            dispute_authority=config.dispute_authority,
        )
    except (KeyError, ValidationError) as exc:
        raise MandatePolicyError("Agreement lacks the terms a payments mandate needs") from exc


class PaymentSettlementData(BaseModel):
    """The seller's acceptance artifact: the derived mandate and its transaction ID."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mandate: Mandate
    transaction_id: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def transaction_names_the_mandate(self) -> PaymentSettlementData:
        if transaction_id(self.mandate) != self.transaction_id:
            raise ValueError("transaction_id is not the hash of the mandate")
        return self

    @classmethod
    def for_agreement(
        cls, agreement: Mapping[str, Any], config: ArkhaiPaymentsConfig
    ) -> PaymentSettlementData:
        mandate = derive_mandate(dict(agreement), mandate_policy_for_agreement(agreement, config))
        return cls(mandate=mandate, transaction_id=transaction_id(mandate))

    @classmethod
    def parse(cls, value: Any) -> PaymentSettlementData:
        try:
            return cls.model_validate(value)
        except ValidationError as exc:
            raise MandatePolicyError("payment settlement data is malformed") from exc

    def to_wire(self) -> dict[str, Any]:
        return {
            "mandate": self.mandate.model_dump(mode="json", by_alias=True, exclude_none=True),
            "transaction_id": self.transaction_id,
        }

    def require_derived_from(
        self, agreement: Mapping[str, Any], config: ArkhaiPaymentsConfig
    ) -> None:
        """Refuse stored data that the accepted Agreement does not derive exactly."""

        if self.to_wire() != PaymentSettlementData.for_agreement(agreement, config).to_wire():
            raise MandatePolicyError("stored payment mandate differs from the accepted Agreement")


__all__ = [
    "PaymentSettlementData",
    "agreement_from_bytes",
    "agreement_payer_account",
    "mandate_policy_for_agreement",
    "selected_payment_option",
]
