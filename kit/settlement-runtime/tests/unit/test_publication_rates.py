"""Exact conversion of a publication rate to base units."""

from __future__ import annotations

import pytest
from market_settlement_runtime import decimal_rate_to_base_units


def test_display_rate_scales_by_the_asset_exponent() -> None:
    assert decimal_rate_to_base_units("174.4", 18) == 174_400_000_000_000_000_000
    assert decimal_rate_to_base_units("2", 2) == 200
    assert decimal_rate_to_base_units("2", 6) == 2_000_000


def test_trailing_zeros_beyond_the_exponent_are_exact() -> None:
    assert decimal_rate_to_base_units("1.2300", 2) == 123


def test_a_rate_longer_than_a_decimal_context_converts_exactly() -> None:
    # 40 significant digits: a 28-digit Decimal context would round this.
    rate = "1234567890123456789012.123456789012345678"
    assert decimal_rate_to_base_units(rate, 18) == int(
        "1234567890123456789012123456789012345678"
    )


def test_a_long_rate_that_is_not_whole_is_refused_rather_than_rounded() -> None:
    rate = "1234567890123456789012.1234567890123456789"  # 19 decimal places
    with pytest.raises(ValueError, match="more than 18 decimal places"):
        decimal_rate_to_base_units(rate, 18)


def test_the_uint256_bound_is_enforced() -> None:
    top = 2**256 - 1
    assert decimal_rate_to_base_units(str(top), 0) == top
    with pytest.raises(ValueError, match="uint256"):
        decimal_rate_to_base_units(str(top + 1), 0)


@pytest.mark.parametrize("rate", ["0", "0.000", "-1", "1e3", "1.", ".5", " 1", "01"])
def test_non_positive_or_non_plain_text_is_refused(rate: str) -> None:
    with pytest.raises(ValueError):
        decimal_rate_to_base_units(rate, 18)


@pytest.mark.parametrize("value", [1.5, 2, None])
def test_non_text_rates_are_refused(value: object) -> None:
    with pytest.raises(ValueError, match="plain decimal text"):
        decimal_rate_to_base_units(value, 18)  # type: ignore[arg-type]


@pytest.mark.parametrize("exponent", [-1, True, 1.0])
def test_exponent_must_be_a_non_negative_integer(exponent: object) -> None:
    with pytest.raises(ValueError, match="exponent"):
        decimal_rate_to_base_units("1", exponent)  # type: ignore[arg-type]
