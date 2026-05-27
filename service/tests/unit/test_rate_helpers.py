"""Unit tests for the rate/literal-field accessor helpers in ``service.schemas``.

Every reader of ``accepted_escrows`` in the storefront/buyer eventually
swaps to ``primary_rate_value()`` / ``accepted_token_address()`` so the
templates wire format ships transparently. These tests pin the
contracts both helpers must honour during the additive-siblings
phase:

  - dict input (the JSON shape coming out of SQLite + the wire),
  - Pydantic ``AcceptedEscrow`` input (the in-memory typed shape),
  - new shape only,
  - legacy shape only (pre-cutover rows),
  - both shapes populated (post-cutover, both emitters live),
  - empty/missing inputs return ``None`` rather than raising.

When Phase 7 drops the legacy fields, the legacy-only and "both
shapes" cases get rewritten to assert against the new shape alone.
"""

from __future__ import annotations

import pytest

from service.schemas import (
    AcceptedEscrow,
    PER_UNIT_SECONDS,
    RateValue,
    accepted_token_address,
    compute_rate_total,
    primary_rate_value,
)


_TOKEN = "0x" + "ab" * 20
_OTHER_TOKEN = "0x" + "cd" * 20
_ESCROW = "0x" + "ee" * 20


# ---------------------------------------------------------------------------
# primary_rate_value
# ---------------------------------------------------------------------------


def test_primary_rate_value_dict_new_shape_int():
    entry = {"rates": [{"field": "amount", "per": "hour", "value": 1234}]}
    assert primary_rate_value(entry) == 1234


def test_primary_rate_value_dict_new_shape_string_uint256():
    entry = {"rates": [{"field": "amount", "per": "hour", "value": "1" + "0" * 30}]}
    assert primary_rate_value(entry) == 10**30


def test_primary_rate_value_dict_legacy_shape_int():
    """Pre-cutover entries in SQLite carry only ``price_per_hour``."""
    entry = {"price_per_hour": 999}
    assert primary_rate_value(entry) == 999


def test_primary_rate_value_dict_legacy_shape_string():
    entry = {"price_per_hour": "999"}
    assert primary_rate_value(entry) == 999


def test_primary_rate_value_both_shapes_prefers_new():
    """Both populated → new shape wins (the post-cutover canonical)."""
    entry = {
        "price_per_hour": "111",
        "rates": [{"field": "amount", "per": "hour", "value": "222"}],
    }
    assert primary_rate_value(entry) == 222


def test_primary_rate_value_hidden_reserve_dict():
    """Hidden reserve = empty rates + ``price_per_hour`` None."""
    entry = {"rates": [], "price_per_hour": None, "literal_fields": {"token": _TOKEN}}
    assert primary_rate_value(entry) is None


def test_primary_rate_value_empty_dict():
    assert primary_rate_value({}) is None


def test_primary_rate_value_pydantic_new_shape():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
        rates=[RateValue(field="amount", per="hour", value=5000)],
    )
    assert primary_rate_value(entry) == 5000


def test_primary_rate_value_pydantic_legacy_shape():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN},
        price_per_hour=42,
    )
    assert primary_rate_value(entry) == 42


# ---------------------------------------------------------------------------
# accepted_token_address
# ---------------------------------------------------------------------------


def test_accepted_token_address_dict_new_shape():
    entry = {"literal_fields": {"token": _TOKEN}}
    assert accepted_token_address(entry) == _TOKEN


def test_accepted_token_address_dict_legacy_shape():
    entry = {"fields": {"token": _TOKEN}}
    assert accepted_token_address(entry) == _TOKEN


def test_accepted_token_address_both_shapes_prefers_new():
    entry = {"literal_fields": {"token": _TOKEN}, "fields": {"token": _OTHER_TOKEN}}
    assert accepted_token_address(entry) == _TOKEN


def test_accepted_token_address_empty():
    assert accepted_token_address({}) is None
    assert accepted_token_address({"fields": {}, "literal_fields": {}}) is None


def test_accepted_token_address_pydantic_new_shape():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        literal_fields={"token": _TOKEN},
        rates=[RateValue(field="amount", per="hour", value=1)],
    )
    assert accepted_token_address(entry) == _TOKEN


def test_accepted_token_address_pydantic_legacy_shape():
    entry = AcceptedEscrow(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN},
        price_per_hour=1,
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
    """Integer division truncates sub-unit fractions, matching the
    prior ``price_per_hour * duration / 3600`` semantics."""
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
