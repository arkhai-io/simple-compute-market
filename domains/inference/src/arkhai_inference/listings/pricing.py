"""The rates an inference listing may advertise.

One credit is one base unit of the settlement asset, so every rate a listing
advertises is exactly one per credit and a purchase of a quantity settles for
that quantity. The rate card prices consumption, not purchase.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from arkhai_api.issuance import MAX_REQUEST_CHARGE
from market_core.schemas import SettlementOption

from arkhai_inference.listings.models import MAX_BASE_UNIT_AMOUNT, InferenceRateCard

UNIT_RATE = 1

#: The rate-card fields that price metered consumption rather than a request.
METERED_RATE_FIELDS = (
    "prompt_credits_per_million",
    "cached_prompt_credits_per_million",
    "completion_credits_per_million",
    "image_credits_per_unit",
)


def non_request_priced_rate(card: InferenceRateCard) -> str | None:
    """The field that keeps ``card`` from a fixed per-request charge, or ``None``.

    Metered rates must be zero, since nothing meters consumption. The request
    charge is at least one (``consume`` refuses less) and at most
    ``MAX_REQUEST_CHARGE``, the canonical-JSON integer bound of the issuance digest.
    """
    for field in METERED_RATE_FIELDS:
        if getattr(card, field):
            return field
    if not 1 <= card.request_credits <= MAX_REQUEST_CHARGE:
        return "request_credits"
    return None


def checked_credit_total(unit_rate: Any, quantity: Any) -> int:
    """Multiply exact integer base units and reject fractions or overflow."""
    if isinstance(unit_rate, bool) or isinstance(quantity, bool):
        raise ValueError("inference rate and quantity must be integers")
    try:
        rate = int(unit_rate)
        count = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("inference rate and quantity must be integers") from exc
    if rate != unit_rate or count != quantity:
        raise ValueError("inference pricing does not admit fractional base units")
    if rate < 0 or count < 1:
        raise ValueError("inference rate must be non-negative and quantity positive")
    total = rate * count
    if total > MAX_BASE_UNIT_AMOUNT:
        raise ValueError("inference quantity-scaled amount exceeds uint256")
    return total


def _check_unit_rate(value: Any, per: Any) -> None:
    if per != "credit":
        raise ValueError("inference settlement rate must be per credit")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if checked_credit_total(value, 1) != UNIT_RATE:
        raise ValueError("inference settlement rate must be exactly one base unit per credit")


def _check_option(option: SettlementOption, asset: str | None) -> None:
    """Refuse an option without one amount rate of one per credit, in ``asset``."""
    if asset is not None and option.price_asset != asset:
        raise ValueError("settlement option asset does not match the rate card's asset")
    amount_rates = [rate for rate in option.price_rates if rate.field == "amount"]
    if len(amount_rates) != 1:
        raise ValueError("an inference settlement option advertises exactly one amount rate")
    _check_unit_rate(amount_rates[0].value, amount_rates[0].per)


def validate_listing_rates(
    settlement_options: Iterable[SettlementOption],
    accepted_escrows: Iterable[dict[str, Any]],
    *,
    asset: str | None = None,
) -> None:
    """Refuse an advertised rate other than one base unit per credit.

    Each settlement option and each accepted escrow advertises exactly one
    amount rate, so a listing that publishes is one a buyer can select and no
    escrow is left to a configured floor to price. An escrow's rate names its
    field and unit, as the selling library reads it. With ``asset`` given,
    also refuse an option or escrow token settling in another asset: the rate
    card's integers are base units of exactly one asset, and a listing taking
    payment in two would let a discovery bound read them in whichever matched.
    An escrow that names no token asserts no asset.
    """
    for option in settlement_options:
        _check_option(option, asset)
    for entry in accepted_escrows:
        literal_fields = entry.get("literal_fields")
        token = literal_fields.get("token") if isinstance(literal_fields, dict) else None
        if asset is not None and token is not None and token != asset:
            raise ValueError("accepted escrow token does not match the rate card's asset")
        amount_rates = [
            rate
            for rate in entry.get("rates") or []
            if isinstance(rate, dict) and rate.get("field") == "amount"
        ]
        if len(amount_rates) != 1:
            raise ValueError("an inference accepted escrow advertises exactly one amount rate")
        _check_unit_rate(amount_rates[0].get("value"), amount_rates[0].get("per"))
