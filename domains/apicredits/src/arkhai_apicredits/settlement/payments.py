"""API-credit vocabulary on the shared Arkhai payments surface: payer and rate validation."""

from __future__ import annotations

from typing import Any

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
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


__all__ = [
    "validate_payer_account",
    "validate_payment_publication_clause",
]
