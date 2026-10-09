"""API-credits listing pricing helpers.

Listings are unit-priced: ``accepted_escrows[*].rates`` carries
``{"field": "amount", "per": "token", "value": <base units>}`` and the
negotiated scalar amount is ``quantity × unit rate``. The
per-unit→absolute translation happens where the seller's reference
amount is computed (the round hook) and, buyer-side, in the policy
surface (work item 5).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from arkhai_apicredits.listings.models import resource_is_api_credits
from market_core.schemas import SettlementOption, SettlementSelection
from market_policy.scalar_policies import selected_settlement_artifact

_MAX_BASE_UNIT_AMOUNT = 2**256 - 1


def _settlement_options(order: dict[str, Any]) -> list[SettlementOption]:
    raw = order.get("settlement_options")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [SettlementOption.model_validate(entry) for entry in (raw or [])]


def checked_credit_total(unit_rate: Any, quantity: Any) -> int:
    """Multiply exact integer base units and reject fractions or overflow."""
    if isinstance(unit_rate, bool) or isinstance(quantity, bool):
        raise ValueError("API-credit rate and quantity must be integers")
    try:
        rate = int(unit_rate)
        count = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("API-credit rate and quantity must be integers") from exc
    if rate != unit_rate or count != quantity:
        raise ValueError("API-credit pricing does not admit fractional base units")
    if rate < 0 or count < 1:
        raise ValueError("API-credit rate must be non-negative and quantity positive")
    total = rate * count
    if total > _MAX_BASE_UNIT_AMOUNT:
        raise ValueError("API-credit quantity-scaled amount exceeds uint256")
    return total


def selected_unit_price(
    order: dict[str, Any],
    selection: SettlementSelection,
) -> int:
    """Return the exact selected option's per-credit base-unit amount."""
    matches = [
        option
        for option in _settlement_options(order)
        if option.option_id == selection.option_id
        and option.mechanism == selection.mechanism
    ]
    if len(matches) != 1:
        raise ValueError("settlement selection does not exact-match one listing option")
    amount_rates = [rate for rate in matches[0].rates if rate.field == "amount"]
    if len(amount_rates) != 1:
        raise ValueError("selected API-credit option requires one amount rate")
    rate = amount_rates[0]
    if rate.per not in {"credit", "token", "request"}:
        raise ValueError("selected API-credit option rate is not per credit")
    return checked_credit_total(rate.value, 1)


def _accepted_escrows(order: dict[str, Any]) -> list[dict[str, Any]]:
    raw = order.get("accepted_escrows")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [entry for entry in (raw or []) if isinstance(entry, dict)]


def _primary_rate_value(entry: dict[str, Any]) -> int | None:
    rates = entry.get("rates")
    if not isinstance(rates, list) or not rates:
        return None
    first = rates[0]
    if not isinstance(first, dict):
        return None
    value = first.get("value")
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _selected_option_rate(option: Mapping[str, Any]) -> int | None:
    """A selected settlement option's per-credit amount, or None if it has none."""
    parsed = SettlementOption.model_validate(option)
    amount_rates = [rate for rate in parsed.rates if rate.field == "amount"]
    if not amount_rates:
        return None
    if len(amount_rates) != 1:
        raise ValueError("selected API-credit option has more than one amount rate")
    rate = amount_rates[0]
    if rate.per not in {"credit", "token", "request"}:
        raise ValueError("selected API-credit option rate is not per credit")
    return checked_credit_total(rate.value, 1)


def extract_unit_price_from_order(
    order: dict[str, Any],
    *,
    default_min_price: Any = None,
    proposal: Mapping[str, Any] | None = None,
) -> int | Fraction:
    """The seller's per-credit floor for the option a buyer's proposal selects.

    The seller negotiates from the selected settlement artifact's rate: the
    settlement option a ``settlement_selection`` names, or the accepted escrow an
    escrow proposal names, which need not be the listing's first. When that
    artifact advertises no rate the listing is a hidden reserve for it and the
    floor is ``[seller.pricing].default_min_price``. Without a proposal that
    selects anything, the listing's first advertised rate stands in. With no
    rate and no floor there is nothing to negotiate against and the negotiation
    is refused. See openspec/specs/negotiation-protocol/spec.md, "The seller's
    reference amount is the selected option's rate".
    """
    selected = selected_settlement_artifact(order, proposal)
    selection = proposal.get("settlement_selection") if isinstance(proposal, Mapping) else None
    if isinstance(selection, Mapping):
        if selected is None:
            raise ValueError("settlement selection does not exact-match one listing option")
        advertised = _selected_option_rate(selected)
    elif selected is not None:
        advertised = _primary_rate_value(selected)
    else:
        accepted = _accepted_escrows(order)
        advertised = _primary_rate_value(accepted[0]) if accepted else None
        if advertised is None:
            options = _settlement_options(order)
            if options:
                amount_rates = [r for r in options[0].rates if r.field == "amount"]
                if len(amount_rates) == 1:
                    advertised = checked_credit_total(amount_rates[0].value, 1)
    if advertised is not None:
        return advertised

    floor = _exact_floor(default_min_price, listing_id=order.get("listing_id"))
    if floor is not None and floor > 0:
        return floor

    raise ValueError(
        f"Listing {order.get('listing_id')} has hidden reserve (the selected "
        "settlement artifact advertises no rate) and "
        "[seller.pricing].default_min_price is not configured. The seller "
        "has no floor to negotiate against; refusing the negotiation."
    )


_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


def _exact_floor(value: Any, *, listing_id: Any) -> Fraction | None:
    """``default_min_price`` as an exact rational, or None when unset.

    Base units reach on-chain settlement, so the floor is parsed from its
    decimal text and never through a binary float.
    """
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise ValueError(
            f"[seller.pricing].default_min_price={value!r} is not a valid number "
            "for an exact floor; state it as decimal text. Hidden-reserve "
            f"listing {listing_id} has no usable floor."
        )
    text = str(value).strip()
    if not text:
        return None
    if not _DECIMAL_TEXT.fullmatch(text):
        raise ValueError(
            f"[seller.pricing].default_min_price={value!r} is not a valid number; "
            f"hidden-reserve listing {listing_id} has no usable floor."
        )
    return Fraction(text)


def determine_strategy_from_order(order: dict[str, Any] | None) -> str | None:
    """Sellers of prepaid credits always maximize the scalar amount."""
    if not order:
        return None
    if resource_is_api_credits(order.get("listing_resource")):
        return "maximize"
    return None
