"""Translate accepted API-credit Agreements into payment mandate policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    MandatePolicy,
    PaymentsOptionParams,
)
from market_arkhai_payments.models import AccountId
from market_settlement_runtime import SettlementPublicationClause


def validate_payer_account(value: Any) -> str:
    return AccountId.model_validate(value).root


def validate_payment_publication_clause(value: Any) -> SettlementPublicationClause:
    """Map supported credit units to the shared integer-base-unit rate surface."""
    clause = SettlementPublicationClause.model_validate(value)
    if (
        clause.mechanism != ARKHAI_PAYMENTS_MECHANISM
        or clause.per not in {"credit", "token", "request"}
        or clause.rate is None
        or not clause.rate.isdigit()
    ):
        raise ValueError("API-credit payment rate must be integer base units per credit")
    return clause


def mandate_policy_from_agreement(
    agreement: Mapping[str, Any],
    *,
    fee_bps: int,
    dispute_authority: str,
    expected_buyer_account: str | None = None,
) -> MandatePolicy:
    """Build exact payment policy from an accepted API-credit Agreement."""
    if not isinstance(agreement, Mapping):
        raise ValueError("accepted Agreement must be an object")
    settlement = agreement.get("settlement")
    if (
        not isinstance(settlement, Mapping)
        or settlement.get("mechanism") != ARKHAI_PAYMENTS_MECHANISM
    ):
        raise ValueError("Agreement does not select arkhai.payments.v1")
    settlement_params = agreement.get("settlement_params")
    payer_account = (
        settlement_params.get("payer_account")
        if isinstance(settlement_params, Mapping)
        else None
    )
    payer_account = validate_payer_account(payer_account)
    if expected_buyer_account is not None and payer_account != expected_buyer_account:
        raise ValueError(
            "Agreement payer account differs from the configured buyer account"
        )
    option = PaymentsOptionParams.model_validate(settlement.get("params"))
    return MandatePolicy(
        buyer_account=payer_account,
        option=option,
        accepted_at=agreement["accepted_at"],
        start_utc=agreement["start_utc"],
        duration_seconds=agreement["duration_seconds"],
        amount=agreement["amount"],
        asset=agreement["asset"],
        fee_bps=fee_bps,
        dispute_authority=dispute_authority,
    )


__all__ = [
    "mandate_policy_from_agreement",
    "validate_payer_account",
    "validate_payment_publication_clause",
]
