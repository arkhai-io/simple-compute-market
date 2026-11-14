"""The bare-metal buyer's quote and its check of the accepted Agreement, with a
per-period option.

The installed payments projection bills once only, so the registry both
functions take holds the payments registration with its projection and presenter
replaced, standing for a mechanism that bills a recurring option: its projection
names the period and its presenter quotes one period through the shared rate
arithmetic. Nothing reads a payment field for the period.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from arkhai_bare_metal_buyer.settlement_stages import purchase_quote, require_quoted_agreement
from market_arkhai_payments import create_arkhai_payments_registration
from market_core.schemas import AgreedPrice, Agreement, PriceBasis, SettlementOption, derive_settlement_option_id
from market_settlement_runtime import SettlementConfigurationRegistry
from market_settlement_runtime.presentation import PaymentPresentation, amount_rate_quote

from test_cli_completion import _BUYER, _SELLER, _option

QUARTER_HOUR = PriceBasis(unit="per_period", period="PT15M", period_seconds=900)
#: 2,500,000 an hour is 625,000 a quarter-hour period.
PERIOD_PRICE = 625_000
#: Two days, 192 periods: a buyer reading the period price as a total, or
#: scaling it by the horizon, would hold the seller to another amount.
HORIZON = 172_800


def _recurring_option() -> SettlementOption:
    option = _option("arkhai.payments.v1", "USD/6", [{"field": "amount", "value": "2500000", "per": "hour"}])
    raw = option.model_dump(mode="json", exclude_none=True)
    raw.pop("option_id")
    raw["settlement"]["period"] = "PT15M"
    return SettlementOption(option_id=derive_settlement_option_id(**raw), **raw)


def _registry() -> SettlementConfigurationRegistry:
    def present(option, duration, quote):
        return PaymentPresentation(
            quote=quote or amount_rate_quote(option, duration, QUARTER_HOUR), setup_once=0, initial_reserve=0,
        )

    return SettlementConfigurationRegistry((replace(
        create_arkhai_payments_registration(),
        project_billing=lambda _option: QUARTER_HOUR, present_payment=present,
    ),))


def _accepted(amount: int, *, duration_seconds: int = HORIZON) -> SimpleNamespace:
    return SimpleNamespace(agreement=Agreement(
        negotiation_id="neg-1", listing_id="listing-1", listing_hash="0" * 64,
        buyer=_BUYER.identity.model_dump(mode="json"), seller=_SELLER.identity.model_dump(mode="json"),
        settlement=_recurring_option(), amount=amount, asset="USD/6", duration_seconds=duration_seconds,
        start_utc="2026-11-12T00:00:00Z", accepted_at="2026-11-12T00:00:00Z",
    ))


def _period_quote(amount: int = PERIOD_PRICE) -> AgreedPrice:
    return AgreedPrice(**QUARTER_HOUR.model_dump(), amount=amount, asset="USD/6")


@pytest.mark.parametrize("duration_seconds", [None, 7200, HORIZON])
def test_a_recurring_quote_is_one_period_s_price_whatever_the_horizon(duration_seconds):
    assert purchase_quote(_recurring_option(), duration_seconds, registry=_registry()) == PERIOD_PRICE


@pytest.mark.parametrize("duration_seconds", [None, HORIZON])
def test_an_agreement_at_one_period_s_quote_is_admitted(duration_seconds):
    require_quoted_agreement(
        _accepted(PERIOD_PRICE), amount=PERIOD_PRICE, duration_seconds=duration_seconds,
        quote=_period_quote(), registry=_registry(),
    )


@pytest.mark.parametrize("amount", [PERIOD_PRICE * 192, PERIOD_PRICE * 48, PERIOD_PRICE + 1])
def test_an_agreement_off_one_period_s_quote_is_refused(amount):
    with pytest.raises(ValueError, match=rf"seller Agreement price {amount} \(per_period\) differs"):
        require_quoted_agreement(
            _accepted(amount), amount=PERIOD_PRICE, duration_seconds=None,
            quote=_period_quote(), registry=_registry(),
        )


def test_a_period_s_price_is_not_admitted_as_a_whole_term_total():
    # A caller holding no quote expects a total; one period's price is not one.
    with pytest.raises(ValueError, match="differs from the quoted 625000 total"):
        require_quoted_agreement(
            _accepted(PERIOD_PRICE), amount=PERIOD_PRICE, duration_seconds=None, registry=_registry(),
        )


def test_an_explicitly_requested_horizon_holds_the_agreement_to_it():
    with pytest.raises(ValueError, match="seller Agreement is for 172800 seconds, not the 7200 requested"):
        require_quoted_agreement(
            _accepted(PERIOD_PRICE), amount=PERIOD_PRICE, duration_seconds=7200,
            quote=_period_quote(), registry=_registry(),
        )
