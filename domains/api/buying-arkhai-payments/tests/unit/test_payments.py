"""Payer selection attaches the buyer's account to the selected payment option."""

from types import SimpleNamespace

import pytest
from core_buyer.negotiation_client import AuthenticatedHTTPError
from market_arkhai_payments import ARKHAI_PAYMENTS_CONFIG_KEY, ARKHAI_PAYMENTS_MECHANISM

import arkhai_api_buying_arkhai_payments.payments as payments
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


def test_a_seller_error_body_never_reaches_the_settlement_events_or_reason(monkeypatch) -> None:
    # A canary secret for this test only; it is not a real key.
    body = {"tenant_credentials": {"key_id": "ak_1", "secret": "sk_canary_in_an_error"}}

    def refused(**_kwargs):
        raise AuthenticatedHTTPError(
            f"GET http://seller/api/v1/settle/n/status -> authenticated HTTP 409: {body}",
            status_code=409, body=body,
        )

    monkeypatch.setattr(payments, "settle_payment", refused)
    events = []
    outcome = SimpleNamespace(
        agreement=SimpleNamespace(model_dump=lambda **_kw: {}), negotiation_id="n",
        agreement_bytes="", settlement_selection=None, settlement_data=None,
        agreed_amount=1, rounds=1,
    )
    result = payments.settle_negotiation(
        negotiation=SimpleNamespace(outcome=outcome, match={"storefront_url": "http://seller"}, attempts=1),
        buyer=None, buy_config=None, settlement_config=None, payer_account="p",
        poll_interval=0, total_timeout=0, on_event=lambda event, fields: events.append((event, fields)),
    )

    assert result.status == "failed"
    assert "sk_canary_in_an_error" not in repr(events) + str(result.reason)
    assert result.reason == "GET http://seller/api/v1/settle/n/status -> authenticated HTTP 409"
