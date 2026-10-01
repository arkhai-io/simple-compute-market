"""The storefront refuses to start with an unreadable configured family rate."""

from __future__ import annotations

import pytest

from market_storefront.startup import _require_readable_family_rates
from tests._settings_overrides import settings_overrides


def test_readable_or_absent_defaults_start():
    _require_readable_family_rates()
    with settings_overrides(
        **{"pricing.defaults.memory.rates": [{"asset": "usd", "rate": "0.05", "per": "hour"}]}
    ):
        _require_readable_family_rates()


def test_an_unreadable_configured_rate_stops_startup():
    with settings_overrides(**{"pricing.defaults.memory.rates": "0.05"}):
        with pytest.raises(RuntimeError, match="pricing.defaults.memory.rates"):
            _require_readable_family_rates()
