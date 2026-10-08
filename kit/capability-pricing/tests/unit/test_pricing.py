"""Pricing a capability shape from per-family rates."""

from __future__ import annotations

import pytest
from market_capability_pricing import (
    FamilyRate,
    PricedFamily,
    PricingProjection,
    ShapePrice,
    linear_price,
    pricing_projection_problems,
)
from market_capability_shape import CapabilitySchema, FieldKind, ShapeField

# A schema and projection shaped like the compute family's, defined here so the
# kit's tests depend on no domain.
SCHEMA = CapabilitySchema(
    fields=(
        ShapeField("gpu", "count", FieldKind.QUANTITY, "gpu_count", required=True),
        ShapeField("gpu", "model", FieldKind.ATTRIBUTE, "gpu_model", required=True),
        ShapeField("cpu", "count", FieldKind.QUANTITY, "vcpu_count"),
        ShapeField("memory", "gib", FieldKind.QUANTITY, "ram_gb"),
        ShapeField("storage", "gib", FieldKind.QUANTITY, "disk_gb"),
    )
)
PROJECTION = PricingProjection(
    {
        "gpu": PricedFamily("count", key="model"),
        "cpu": PricedFamily("count"),
        "memory": PricedFamily("gib"),
        "storage": PricedFamily("gib"),
    }
)
RATES = {
    "gpu": FamilyRate("80", "hour"),
    "cpu": FamilyRate("0.5", "hour"),
    "memory": FamilyRate("0.05", "hour"),
    "storage": FamilyRate("0.001", "hour"),
}
SHAPE = {"gpu": {"count": 2, "model": "H100"}, "cpu": {"count": 16}, "memory": {"gib": 128}}


def test_worked_example_prices_every_named_family() -> None:
    assert linear_price(SHAPE, RATES, PROJECTION) == ShapePrice("174.4", "hour")


def test_the_same_rates_price_a_different_shape() -> None:
    shape = {"gpu": {"count": 8, "model": "H100"}, "storage": {"gib": 1000}}
    assert linear_price(shape, RATES, PROJECTION) == ShapePrice("641", "hour")


def test_a_named_family_without_a_rate_contributes_nothing() -> None:
    rates = {"gpu": RATES["gpu"], "cpu": RATES["cpu"]}
    assert linear_price(SHAPE, rates, PROJECTION) == ShapePrice("168", "hour")


def test_no_applicable_rate_is_a_zero_price() -> None:
    price = linear_price(SHAPE, {"storage": RATES["storage"]}, PROJECTION)
    assert price == ShapePrice("0", None)
    assert price.is_zero


def test_an_omitted_family_is_not_priced() -> None:
    shape = {"gpu": {"count": 1, "model": "H100"}}
    assert linear_price(shape, RATES, PROJECTION) == ShapePrice("80", "hour")


def test_a_price_longer_than_a_decimal_context_is_exact() -> None:
    rates = {
        "gpu": FamilyRate("1234567890123456789012.123456789012345678", "hour"),
        "memory": FamilyRate("0.000000000000000001", "hour"),
    }
    shape = {"gpu": {"count": 3, "model": "H100"}, "memory": {"gib": 7}}
    assert linear_price(shape, rates, PROJECTION) == ShapePrice(
        "3703703670370370367036.370370367037037041", "hour"
    )


def test_a_fractional_total_below_one_is_rendered_without_an_exponent() -> None:
    rates = {"gpu": FamilyRate("0.00001", "hour")}
    assert linear_price({"gpu": {"count": 3, "model": "A"}}, rates, PROJECTION) == (
        ShapePrice("0.00003", "hour")
    )


@pytest.mark.parametrize("rate", ["0", "0.00", "-1", "1e3", "1.", "01", " 1"])
def test_zero_and_malformed_rates_are_refused(rate: str) -> None:
    with pytest.raises(ValueError):
        FamilyRate(rate, "hour")


@pytest.mark.parametrize("rate", [1.5, 2, None])
def test_non_text_rates_are_refused(rate: object) -> None:
    with pytest.raises(ValueError, match="decimal text"):
        FamilyRate(rate, "hour")  # type: ignore[arg-type]


def test_rates_naming_different_units_are_refused() -> None:
    rates = {"gpu": FamilyRate("1", "hour"), "cpu": FamilyRate("1", "day")}
    shape = {"gpu": {"count": 1, "model": "A"}, "cpu": {"count": 1}}
    with pytest.raises(ValueError, match="different units"):
        linear_price(shape, rates, PROJECTION)


def test_a_rate_for_a_family_nothing_prices_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing prices"):
        linear_price(SHAPE, {"fpga": FamilyRate("1", "hour")}, PROJECTION)


def test_a_projection_agreeing_with_its_schema_has_no_problems() -> None:
    assert pricing_projection_problems(PROJECTION, SCHEMA) == []


def test_a_projection_disagreeing_with_its_schema_is_reported() -> None:
    projection = PricingProjection(
        {"gpu": PricedFamily("model", key="count"), "fpga": PricedFamily("count")}
    )
    assert pricing_projection_problems(projection, SCHEMA) == [
        "gpu.model is not a quantity field",
        "gpu.count is not an attribute field",
        "fpga.count is not a quantity field",
    ]
