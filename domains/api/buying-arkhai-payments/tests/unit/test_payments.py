"""Payer selection attaches the buyer's account to the selected payment option."""

from types import SimpleNamespace

import pytest
from market_arkhai_payments import ARKHAI_PAYMENTS_CONFIG_KEY, ARKHAI_PAYMENTS_MECHANISM

from arkhai_api_buying_arkhai_payments.payments import (
    configured_payer_account,
    payment_selection_for_listing,
    serviceable_payments_config,
)


def test_payment_selection_attaches_buyer_account_without_alkahest_resources() -> None:
    account = "00000000-0000-4000-8000-000000000011"
    option_id = "a" * 64

    class Config:
        def mechanism_config(self, key):
            assert key == ARKHAI_PAYMENTS_CONFIG_KEY
            return SimpleNamespace(enabled=True)

    class Policy:
        config = Config()

        def compatible_options(self, advertised):
            assert tuple(advertised) == ({"option_id": option_id},)
            registration = SimpleNamespace(mechanism_id=ARKHAI_PAYMENTS_MECHANISM)
            option = SimpleNamespace(
                mechanism=ARKHAI_PAYMENTS_MECHANISM, option_id=option_id
            )
            return ((registration, option),)

    selection = payment_selection_for_listing(
        Policy(),
        {"settlement_options": [{"option_id": option_id}]},
        expiration_unix=1_800_000_000,
        payer_account=account,
        prefer_payment=True,
    )

    assert selection is not None
    assert selection.mechanism == ARKHAI_PAYMENTS_MECHANISM
    assert selection.option_id == option_id
    assert selection.params == {"payer_account": account}


def test_the_payer_account_is_read_from_its_section() -> None:
    account = "00000000-0000-4000-8000-000000000011"
    assert configured_payer_account(
        "example", lambda: {"example": {"payer_account": account}}
    ) == account
    with pytest.raises(ValueError, match=r"\[example\] must be a table"):
        configured_payer_account("example", lambda: {"example": "not a table"})


def test_an_accepted_payment_completes_under_a_disabled_section_but_not_an_absent_one() -> None:
    disabled = SimpleNamespace(enabled=False)
    sections = {ARKHAI_PAYMENTS_CONFIG_KEY: disabled}
    config = SimpleNamespace(mechanism_config=lambda key: sections.get(key))
    assert serviceable_payments_config(config) is disabled
    sections.clear()
    with pytest.raises(ValueError, match="not configured"):
        serviceable_payments_config(config)
