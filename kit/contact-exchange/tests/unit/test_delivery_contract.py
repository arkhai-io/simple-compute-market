"""Exact private carriers and absent-policy option identity compatibility."""

import pytest
from market_contact_exchange import (
    ContactProfile,
    ContactSettlementConfig,
    contact_buyer_compatibility,
)
from market_contact_exchange.delivery_contract import (
    DELIVERY_POLICY,
    ContactDeliveryConfig,
    EmailRoute,
    IntroductionReview,
    bound_payload,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    "address",
    [
        "a@example.invalid",
        "A+b.c@Sub.Example.invalid",
        "a!#$%&'*+-/=?^_`{|}~@example.invalid",
    ],
)
def test_mailbox_preserves_spelling(address):
    assert EmailRoute(kind="email", address=address).address == address


@pytest.mark.parametrize(
    "address",
    [
        "",
        "x@y",
        "A <a@example.invalid>",
        "a@example.invalid,b@example.invalid",
        "a..b@example.invalid",
        "a@-example.invalid",
        "a@example.invalid.",
        "a@127.0.0.1\r\nBcc: x@example.invalid",
        "é@example.invalid",
        "a@例.invalid",
        '"a"@example.invalid',
        "a@[127.0.0.1]",
        "a" * 65 + "@example.invalid",
        "a@" + "b" * 64 + ".invalid",
        "a @example.invalid",
    ],
)
def test_mailbox_rejects_unsupported_syntax(address):
    with pytest.raises(ValidationError):
        EmailRoute(kind="email", address=address)


def test_policy_absence_is_omitted_and_null_and_unknown_fail_closed():
    assert ContactProfile(channel="x", terms="y").model_dump() == {
        "channel": "x",
        "terms": "y",
    }
    with pytest.raises(ValidationError):
        ContactProfile(channel="x", terms="y", delivery_policy=None)
    config = ContactSettlementConfig(enabled=True)
    option = {
        "mechanism": "contact-exchange.v1",
        "asset": "introduction",
        "rates": [],
        "params": {"delivery_policy": {"kind": "future"}},
    }
    assert not contact_buyer_compatibility(config, option, {})
    option["params"]["delivery_policy"] = DELIVERY_POLICY.model_dump()
    assert contact_buyer_compatibility(config, option, {})


def test_contact_unicode_scalars_and_no_normalization():
    values = {"name😀": '  É\\\n"😀  '}
    assert bound_payload(values) == values
    for value in ({"x": "\ud800"}, {"\udfff": "x"}, {"x": " \t\n"}):
        with pytest.raises(ValueError):
            bound_payload(value)


def test_review_rejects_coercion_unknown_fields_and_empty_payload():
    body = dict(
        schema_version=2,
        negotiation_id="n-1",
        obligation_ref="a" * 64,
        finalization_id="12345678-1234-4234-8234-123456789abc",
        contact_payload={"name": "Synthetic Buyer"},
        delivery_route={"kind": "email", "address": "buyer@example.invalid"},
    )
    assert IntroductionReview.model_validate(body).model_dump() == body
    for delta in (
        {"schema_version": 2.0},
        {"schema_version": "2"},
        {"negotiation_id": "n/1"},
        {"contact_payload": {}},
        {"finalization_id": body["finalization_id"].upper()},
        {"seller_route": body["delivery_route"]},
    ):
        with pytest.raises(ValidationError):
            IntroductionReview.model_validate({**body, **delta})


def test_config_is_strict_and_errors_hide_input():
    body = dict(
        schema_version=2,
        mode="two-sided-contact",
        seller_route={"kind": "email", "address": "seller@example.invalid"},
        smtp=dict(
            host="smtp.example.invalid",
            port=587,
            sender="sender@example.invalid",
            username="synthetic-user",
            password="synthetic-password",
            timeout_seconds=10,
        ),
    )
    assert ContactDeliveryConfig.model_validate(body)
    for delta in (
        {"host": "https://example.invalid"},
        {"host": "127.0.0.1"},
        {"timeout_seconds": 10.0},
        {"password": "SECRET-CANARY\r\n"},
        {"start_tls": False},
    ):
        with pytest.raises(ValidationError) as error:
            ContactDeliveryConfig.model_validate(
                {**body, "smtp": {**body["smtp"], **delta}}
            )
        assert "SECRET-CANARY" not in str(error.value)
