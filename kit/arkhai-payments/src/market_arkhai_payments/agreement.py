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

from market_core.schemas import (
    settlement_option_asset,
    settlement_option_lifecycle,
    settlement_option_params,
    settlement_option_schema,
)

from market_deal_lifecycle.terms import LifecycleTerms
from market_arkhai_payments.canonical import wire_json
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
    if not isinstance(selected, Mapping) or settlement_option_schema(selected) != ARKHAI_PAYMENTS_MECHANISM:
        raise MandatePolicyError(f"Agreement does not select {ARKHAI_PAYMENTS_MECHANISM}")
    if settlement_option_asset(selected) != agreement.get("asset"):
        raise MandatePolicyError(
            "Agreement asset differs from the selected payments price"
        )
    try:
        return PaymentsOptionParams.model_validate(settlement_option_params(selected))
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

    if config.fee_bps is None:
        raise MandatePolicyError("payments fee policy is required")
    return _policy(
        agreement,
        fee_bps=config.fee_bps,
        expected_payer=expected_payer,
    )


def _policy(
    agreement: Mapping[str, Any],
    *,
    fee_bps: int,
    expected_payer: str | None = None,
) -> MandatePolicy:
    payer = agreement_payer_account(agreement)
    if expected_payer is not None and payer != expected_payer:
        raise MandatePolicyError("Agreement names a different payer account")
    try:
        lifecycle = LifecycleTerms.model_validate(
            settlement_option_lifecycle(agreement.get("settlement"))
        )
        AccountId.model_validate(lifecycle.adjudication.dispute.account)
    except ValidationError as exc:
        raise MandatePolicyError(
            "selected payments option requires lifecycle.adjudication.dispute "
            "with a valid payments account"
        ) from exc
    try:
        return MandatePolicy(
            buyer_account=payer,
            option=selected_payment_option(agreement),
            accepted_at=agreement["accepted_at"],
            start_utc=agreement["start_utc"],
            duration_seconds=agreement["duration_seconds"],
            amount=agreement["amount"],
            asset=agreement["asset"],
            fee_bps=fee_bps,
            lifecycle=lifecycle,
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
            "mandate": wire_json(self.mandate),
            "transaction_id": self.transaction_id,
        }

    def require_bound_to(self, agreement: Mapping[str, Any]) -> None:
        """Refuse stored data that the accepted Agreement does not bind exactly.

        The fee is read from the stored mandate because it was trusted policy
        at acceptance; later configuration must not reinterpret an accepted
        transaction. The dispute authority comes from the accepted option's
        lifecycle terms, never from current configuration. Everything the
        Agreement fixes (deal hash, payer, payee, amount, asset, hold, expiry) is re-derived and
        compared exactly; the transaction ID already hashes the whole mandate.
        """

        wire = self.to_wire()["mandate"]
        try:
            policy = _policy(
                agreement,
                fee_bps=int(wire["fee"]["bps"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MandatePolicyError("stored payment mandate is malformed") from exc
        derived = derive_mandate(dict(agreement), policy)
        if wire_json(derived) != wire:
            raise MandatePolicyError("stored payment mandate differs from the accepted Agreement")


__all__ = [
    "PaymentSettlementData",
    "agreement_from_bytes",
    "agreement_payer_account",
    "mandate_policy_for_agreement",
    "selected_payment_option",
]
