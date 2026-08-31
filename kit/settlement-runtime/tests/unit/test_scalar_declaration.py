from __future__ import annotations

from dataclasses import replace

import pytest
from market_settlement_runtime.configuration import (
    SettlementConfigurationError,
    reject_scalar_rates_for_non_scalar,
)

from test_configuration import _registration


def test_registration_declares_scalar_by_default() -> None:
    assert _registration().negotiates_scalar_amount is True


def test_registration_can_decline_scalar() -> None:
    declined = replace(_registration(), negotiates_scalar_amount=False)
    assert declined.negotiates_scalar_amount is False


def test_non_scalar_options_must_not_advertise_amount_rate() -> None:
    built = {
        "accepted_escrows": [],
        "settlement_options": [
            {
                "option_id": "aa" * 32,
                "mechanism": "demo.pay.v1",
                "asset": "usd",
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
                "params": {},
            }
        ],
    }
    with pytest.raises(SettlementConfigurationError, match="declines scalar"):
        reject_scalar_rates_for_non_scalar("demo.pay.v1", built)


def test_non_scalar_options_without_amount_rate_pass() -> None:
    built = {
        "accepted_escrows": [],
        "settlement_options": [
            {
                "option_id": "bb" * 32,
                "mechanism": "demo.pay.v1",
                "asset": "introduction",
                "rates": [],
                "params": {"terms": "prose"},
            }
        ],
    }
    reject_scalar_rates_for_non_scalar("demo.pay.v1", built)


def test_non_mapping_builder_output_is_ignored() -> None:
    reject_scalar_rates_for_non_scalar("demo.pay.v1", None)
    reject_scalar_rates_for_non_scalar("demo.pay.v1", [1, 2, 3])
