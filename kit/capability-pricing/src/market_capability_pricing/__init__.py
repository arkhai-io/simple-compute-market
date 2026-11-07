"""Pricing a capability shape from per-family rates.

A seller states, for each family it prices, a rate per unit of that family per
time unit, in one asset's display units: ``{"gpu": FamilyRate("80", "hour"),
"memory": FamilyRate("0.05", "hour")}``. An aggregator turns a shape and those
rates into one price for the whole shape.

What a family is priced by is the domain's statement, not an inference from its
capability schema: a ``PricingProjection`` names each family a rate may be
stated for, the one quantity field it is priced by, and, for a family priced per
attribute value, that attribute. ``pricing_projection_problems`` checks a
projection against the schema it describes.

The aggregator is an interface, not a formula. Real capacity is not linearly
priced, so a domain may select a different aggregator; no caller may
reconstruct a total by multiplying a family's rate by its quantity, because that
shortcut agrees with the linear aggregator and with no other.

Every amount here is exact. Rates are decimal text parsed digit by digit into
integers, never through ``float`` and never through ``Decimal`` arithmetic under
a precision context, so a price longer than such a context still comes out
exact. Converting a price to an asset's base units is the caller's step, under
the caller's rounding rule. See openspec/specs/storefront-publication/spec.md,
"Price aggregation is replaceable".
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from market_capability_shape import CapabilitySchema, FieldKind

_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_UNIT = re.compile(r"[a-z][a-z0-9_-]*")


def _exact(text: Any, *, what: str) -> tuple[int, int]:
    """Decimal text as ``(coefficient, scale)``, meaning ``coefficient / 10**scale``."""
    if not isinstance(text, str) or not _DECIMAL_TEXT.fullmatch(text):
        raise ValueError(f"{what} {text!r} is not plain decimal text")
    whole, _, fraction = text.partition(".")
    return int(whole + fraction), len(fraction)


def _decimal_text(coefficient: int, scale: int) -> str:
    """The exponent-free decimal text of ``coefficient / 10**scale``."""
    digits = str(coefficient).rjust(scale + 1, "0")
    if scale == 0:
        return digits
    whole, fraction = digits[:-scale], digits[-scale:].rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


@dataclass(frozen=True)
class FamilyRate:
    """One family's rate: ``rate`` per unit of the family per ``per``.

    ``rate`` is positive decimal text in an asset's display units. Zero is
    refused: a family the seller does not charge for is one it states no rate
    for.
    """

    rate: str
    per: str

    def __post_init__(self) -> None:
        coefficient, _ = _exact(self.rate, what="family rate")
        if coefficient <= 0:
            raise ValueError(f"family rate {self.rate!r} must be positive")
        if not isinstance(self.per, str) or not _UNIT.fullmatch(self.per):
            raise ValueError(f"family rate unit {self.per!r} is not a canonical unit")


@dataclass(frozen=True)
class PricedFamily:
    """How one family is priced: by ``quantity``, and per ``key`` value if set."""

    quantity: str
    key: str | None = None


@dataclass(frozen=True)
class PricingProjection:
    """The families a domain prices, each by one quantity, optionally per key."""

    families: Mapping[str, PricedFamily]

    def __post_init__(self) -> None:
        object.__setattr__(self, "families", MappingProxyType(dict(self.families)))

    def key_of(self, family: str) -> str | None:
        """The attribute ``family`` is priced per, or None if it is not keyed."""
        return self.families[family].key


def pricing_projection_problems(
    projection: PricingProjection, schema: CapabilitySchema
) -> list[str]:
    """Every way ``projection`` disagrees with the schema it prices.

    A priced family's quantity must be a quantity field of that family, and its
    key, if any, one of that family's attributes.
    """
    problems: list[str] = []
    for family, priced in projection.families.items():
        quantity = schema.lookup(family, priced.quantity)
        if quantity is None or quantity.kind is not FieldKind.QUANTITY:
            problems.append(f"{family}.{priced.quantity} is not a quantity field")
        if priced.key is not None:
            key = schema.lookup(family, priced.key)
            if key is None or key.kind is not FieldKind.ATTRIBUTE:
                problems.append(f"{family}.{priced.key} is not an attribute field")
    return problems


@dataclass(frozen=True)
class ShapePrice:
    """A shape's exact price: ``amount`` display units per ``per``.

    ``amount`` is ``"0"`` when no family the shape names has a rate; whether a
    zero price is acceptable is the caller's decision.
    """

    amount: str
    per: str | None

    @property
    def is_zero(self) -> bool:
        return _exact(self.amount, what="price")[0] == 0


class PriceAggregator(Protocol):
    """Price a shape from one asset's family rates."""

    def __call__(
        self,
        shape: Mapping[str, Mapping[str, Any]],
        rates: Mapping[str, FamilyRate],
        projection: PricingProjection,
    ) -> ShapePrice: ...


def linear_price(
    shape: Mapping[str, Mapping[str, Any]],
    rates: Mapping[str, FamilyRate],
    projection: PricingProjection,
) -> ShapePrice:
    """Sum, over the families ``shape`` names that have a rate, quantity times rate.

    A family the shape names without a rate contributes nothing: stating a
    quantity commits it, and does not mean the seller charges for it. A family
    the shape omits is not priced, whether or not a rate is stated for it.
    Raises ``ValueError`` for a rate stated for a family the projection does not
    price, rates naming different units, a value that is not a ``FamilyRate``,
    and a shape naming a priced family without its quantity.
    """
    unpriced = sorted(family for family in rates if family not in projection.families)
    if unpriced:
        raise ValueError(f"rates are stated for families nothing prices: {unpriced}")
    applicable = sorted(family for family in shape if family in rates)
    terms: list[tuple[int, int]] = []
    units: set[str] = set()
    for family in applicable:
        rate = rates[family]
        if not isinstance(rate, FamilyRate):
            raise ValueError(f"family {family!r} rate is not a FamilyRate")
        field = projection.families[family].quantity
        quantity = shape[family].get(field)
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError(
                f"shape names family {family!r} without a positive {field!r}"
            )
        coefficient, scale = _exact(rate.rate, what="family rate")
        terms.append((coefficient * quantity, scale))
        units.add(rate.per)
    if len(units) > 1:
        raise ValueError(f"family rates name different units: {sorted(units)}")
    if not terms:
        return ShapePrice(amount="0", per=None)
    scale = max(term_scale for _, term_scale in terms)
    total = sum(value * 10 ** (scale - term_scale) for value, term_scale in terms)
    return ShapePrice(amount=_decimal_text(total, scale), per=units.pop())


__all__ = [
    "FamilyRate",
    "PriceAggregator",
    "PricedFamily",
    "PricingProjection",
    "ShapePrice",
    "linear_price",
    "pricing_projection_problems",
]
