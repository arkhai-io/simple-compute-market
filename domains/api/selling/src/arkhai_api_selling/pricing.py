"""Per-credit pricing: a listing's amount is ``quantity × rate``, exact in integer base units."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from market_core.schemas import SettlementOption
from market_policy.scalar_policies import selected_settlement_artifact

from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.issuance import decode_stored

_MAX_BASE_UNIT_AMOUNT = 2**256 - 1
_PER_CREDIT = frozenset({"credit", "token", "request"})


def domain_listing_resource(
    contributions: SellingContributions, value: Any
) -> dict[str, Any] | None:
    """``value`` as the domain's listing schema reads it, or None when it is not the domain's."""
    try:
        listing = contributions.listing_schema.model_validate(
            {"listing_resource": decode_stored(value)}
        )
    except ValueError:
        return None
    return listing.listing_resource.model_dump(mode="json")


def _settlement_options(order: dict[str, Any]) -> list[SettlementOption]:
    raw = order.get("settlement_options")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [SettlementOption.model_validate(entry) for entry in (raw or [])]


def checked_credit_total(unit_rate: Any, quantity: Any, *, noun: str) -> int:
    """Multiply exact integer base units and reject fractions or overflow."""
    if isinstance(unit_rate, bool) or isinstance(quantity, bool):
        raise ValueError(f"{noun} rate and quantity must be integers")
    try:
        rate = int(unit_rate)
        count = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{noun} rate and quantity must be integers") from exc
    if rate != unit_rate or count != quantity:
        raise ValueError(f"{noun} pricing does not admit fractional base units")
    if rate < 0 or count < 1:
        raise ValueError(f"{noun} rate must be non-negative and quantity positive")
    total = rate * count
    if total > _MAX_BASE_UNIT_AMOUNT:
        raise ValueError(f"{noun} quantity-scaled amount exceeds uint256")
    return total


def _accepted_escrows(order: dict[str, Any]) -> list[dict[str, Any]]:
    raw = order.get("accepted_escrows")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [entry for entry in (raw or []) if isinstance(entry, dict)]


def _escrow_rate(escrow: Mapping[str, Any], *, noun: str) -> int | None:
    """An escrow's one per-credit amount rate, or None when it states no amount rate."""
    rates = escrow.get("rates")
    amount_rates = [
        rate
        for rate in (rates if isinstance(rates, list) else ())
        if isinstance(rate, Mapping) and rate.get("field") == "amount"
    ]
    if not amount_rates:
        return None
    if len(amount_rates) != 1:
        raise ValueError(f"selected {noun} escrow has more than one amount rate")
    rate = amount_rates[0]
    if rate.get("per") not in _PER_CREDIT:
        raise ValueError(f"selected {noun} escrow rate is not per credit")
    value = rate.get("value")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    return checked_credit_total(value, 1, noun=noun)


def _option_rate(option: Mapping[str, Any], *, noun: str) -> int | None:
    """A settlement option's one per-credit amount rate, or None when it states no amount rate."""
    parsed = SettlementOption.model_validate(option)
    amount_rates = [rate for rate in parsed.rates if rate.field == "amount"]
    if not amount_rates:
        return None
    if len(amount_rates) != 1:
        raise ValueError(f"selected {noun} option has more than one amount rate")
    rate = amount_rates[0]
    if rate.per not in _PER_CREDIT:
        raise ValueError(f"selected {noun} option rate is not per credit")
    return checked_credit_total(rate.value, 1, noun=noun)


def setting_text(key: str) -> str:
    """How a refusal names a dotted setting: its table bracketed, then its key."""
    table, _, name = key.rpartition(".")
    return f"[{table}].{name}" if table else f"[{name}]"


def extract_unit_price_from_order(
    order: dict[str, Any],
    *,
    noun: str,
    floor_key: str,
    default_min_price: Any = None,
    proposal: Mapping[str, Any] | None = None,
) -> int | Fraction:
    """The seller's per-credit floor for the option a buyer's proposal selects.

    The selected option's or escrow's amount rate, else the configured floor where it
    states none; with neither the negotiation is refused. ``floor_key`` is the
    floor setting as the composing storefront spells it, which a refusal names.
    See openspec/specs/negotiation-protocol/spec.md, "The seller's reference
    amount is the selected option's rate".
    """
    selected = selected_settlement_artifact(order, proposal)
    selection = proposal.get("settlement_selection") if isinstance(proposal, Mapping) else None
    if isinstance(selection, Mapping):
        if selected is None:
            raise ValueError("settlement selection does not exact-match one listing option")
        advertised = _option_rate(selected, noun=noun)
    elif selected is not None:
        advertised = _escrow_rate(selected, noun=noun)
    else:
        accepted = _accepted_escrows(order)
        advertised = _escrow_rate(accepted[0], noun=noun) if accepted else None
        if advertised is None:
            options = _settlement_options(order)
            if options:
                amount_rates = [r for r in options[0].rates if r.field == "amount"]
                if len(amount_rates) == 1:
                    advertised = checked_credit_total(amount_rates[0].value, 1, noun=noun)
    if advertised is not None:
        return advertised

    setting = setting_text(floor_key)
    floor = _exact_floor(default_min_price, setting=setting, listing_id=order.get("listing_id"))
    if floor is not None and floor > 0:
        return floor

    raise ValueError(
        f"Listing {order.get('listing_id')} has hidden reserve (the selected "
        f"settlement artifact advertises no rate) and {setting} is not "
        "configured. The seller has no floor to negotiate against; refusing "
        "the negotiation."
    )


_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


def _exact_floor(value: Any, *, setting: str, listing_id: Any) -> Fraction | None:
    """The configured floor as an exact rational parsed from decimal text, or None when unset."""
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise ValueError(
            f"{setting}={value!r} is not a valid number for an exact floor; "
            "state it as decimal text. Hidden-reserve "
            f"listing {listing_id} has no usable floor."
        )
    text = str(value).strip()
    if not text:
        return None
    if not _DECIMAL_TEXT.fullmatch(text):
        raise ValueError(
            f"{setting}={value!r} is not a valid number; "
            f"hidden-reserve listing {listing_id} has no usable floor."
        )
    return Fraction(text)


def determine_strategy(
    contributions: SellingContributions, order: Mapping[str, Any] | None
) -> str | None:
    """Sellers of prepaid credits always maximize the scalar amount of their own listings."""
    if not order:
        return None
    if domain_listing_resource(contributions, order.get("listing_resource")) is not None:
        return "maximize"
    return None
