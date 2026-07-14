"""Unit tests for the rate/literal-field accessor helpers in ``market_core.schemas``.

Every reader of ``accepted_escrows`` eventually swaps to
``primary_rate_value()`` / ``accepted_token_address()`` so the templates
wire format ships transparently. These tests pin the contracts both
helpers must honour:

  - dict input (the JSON shape coming out of SQLite + the wire),
  - Pydantic ``AcceptedEscrow`` input (the in-memory typed shape),
  - empty/missing inputs return ``None`` rather than raising.
"""

from __future__ import annotations

import pytest

from market_core.schemas import (
    AcceptedEscrow,
    PER_UNIT_SECONDS,
    RateValue,
    accepted_token_address,
    compute_rate_total,
    primary_rate_value,
)


_TOKEN = "0x" + "ab" * 20
_ESCROW = "0x" + "ee" * 20


# ---------------------------------------------------------------------------
# primary_rate_value
# ---------------------------------------------------------------------------


def test_primary_rate_value_dict_int():
    entry = {"rates": [{"field": "amount", "per": "hour", "value": 1234}]}
    assert primary_rate_value(entry) == 1234


def test_primary_rate_value_dict_string_uint256():
    entry = {"rates": [{"field": "amount", "per": "hour", "value": "1" + "0" * 30}]}
    assert primary_rate_value(entry) == 10**30


def test_primary_rate_value_hidden_reserve_dict():
    """Hidden reserve = empty ``rates``."""
    entry = {"rates": [], "literal_fields": {"token": _TOKEN}}
    assert primary_rate_value(entry) is None


def test_primary_rate_value_empty_dict():
    assert primary_rate_value({}) is None


def test_primary_rate_value_pydantic():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
        rates=[RateValue(field="amount", per="hour", value=5000)],
    )
    assert primary_rate_value(entry) == 5000


def test_primary_rate_value_pydantic_hidden_reserve():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
    )
    assert primary_rate_value(entry) is None


# ---------------------------------------------------------------------------
# accepted_token_address
# ---------------------------------------------------------------------------


def test_accepted_token_address_dict():
    entry = {"literal_fields": {"token": _TOKEN}}
    assert accepted_token_address(entry) == _TOKEN


def test_accepted_token_address_empty():
    assert accepted_token_address({}) is None
    assert accepted_token_address({"literal_fields": {}}) is None


def test_accepted_token_address_pydantic():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
        rates=[RateValue(field="amount", per="hour", value=1)],
    )
    assert accepted_token_address(entry) == _TOKEN


# ---------------------------------------------------------------------------
# compute_rate_total
# ---------------------------------------------------------------------------


def test_compute_rate_total_full_hour():
    rate = RateValue(field="amount", per="hour", value=1000)
    assert compute_rate_total(rate, 3600) == 1000


def test_compute_rate_total_two_hours():
    rate = RateValue(field="amount", per="hour", value=1000)
    assert compute_rate_total(rate, 7200) == 2000


def test_compute_rate_total_partial_hour_truncates():
    """Integer division truncates sub-unit fractions."""
    rate = RateValue(field="amount", per="hour", value=1000)
    assert compute_rate_total(rate, 1800) == 500  # half hour
    assert compute_rate_total(rate, 3599) == 999  # truncated, not rounded


def test_compute_rate_total_unknown_unit_raises():
    rate = RateValue(field="amount", per="hour", value=1000)
    object.__setattr__(rate, "per", "request")  # bypass validator
    with pytest.raises(ValueError, match="unknown rate.per unit"):
        compute_rate_total(rate, 3600)


def test_per_unit_seconds_includes_hour():
    assert PER_UNIT_SECONDS["hour"] == 3600
