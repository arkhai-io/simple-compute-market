"""The shared payments helper blocks only an absent or unready payments target.

A pipeline configures no payments target, so its payment scenarios are blocked.
Once a target is configured, the run is expected to supply everything else, and
a missing setting fails rather than hiding a broken configuration behind a skip.
Every value below is a development fixture, never used on any network.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.roles.helpers import payments

Failed = pytest.fail.Exception
Skipped = pytest.skip.Exception

_COMPLETE = {
    "SERVICE_URL": "http://127.0.0.1:9",
    "SERVICE_IDENTITY": "A" * 43,
    "DISPUTE_AUTHORITY": "33333333-3333-4333-8333-333333333333",
    "BUYER_ACCOUNT": "11111111-1111-4111-8111-111111111111",
    "BUYER_MARKETPLACE_CREDENTIAL": "11" * 32,
    "SELLER_MARKETPLACE_CREDENTIAL": "22" * 32,
    "DEVELOPMENT_AUTH": True,
}


class _Settings:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = {f"PAYMENTS.{key}": value for key, value in values.items()}

    def get(self, key: str, default: object = None) -> object:
        return self._values.get(key, default)


@pytest.fixture
def configure(monkeypatch):
    def _configure(**values: Any) -> None:
        monkeypatch.setattr(payments, "settings", _Settings(values))

    return _configure


def _never_asked(_url: str) -> bool:
    raise AssertionError("readiness must not be checked")


def _outcome(**kwargs: Any) -> BaseException:
    """The skip or failure `configured_payments` raises, caught so that a wrong
    skip fails this test instead of being reported as a skipped test."""
    try:
        payments.configured_payments(**kwargs)
    except (Skipped, Failed) as raised:
        return raised
    raise AssertionError("configured_payments neither skipped nor failed")


def test_no_configured_target_blocks(configure) -> None:
    configure()
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Skipped)
    assert "blocked: PAYMENTS.SERVICE_URL not configured" in str(outcome)


def test_a_configured_target_missing_a_buyer_credential_fails(configure) -> None:
    values = dict(_COMPLETE)
    del values["BUYER_MARKETPLACE_CREDENTIAL"]
    configure(**values)
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Failed)
    assert "PAYMENTS.BUYER_MARKETPLACE_CREDENTIAL not configured" in str(outcome)


def test_an_unready_target_blocks(configure) -> None:
    configure(**_COMPLETE)
    outcome = _outcome(ready=lambda _url: False)
    assert isinstance(outcome, Skipped)
    assert "blocked: payments service at http://127.0.0.1:9" in str(outcome)


def test_a_ready_target_yields_its_policy(configure) -> None:
    configure(**_COMPLETE)
    config = payments.configured_payments(ready=lambda _url: True)
    assert config.service_url == "http://127.0.0.1:9"
    assert config.development_auth is True
    assert config.livemode is False


@pytest.mark.parametrize("flag", ["LIVEMODE", "DEVELOPMENT_AUTH"])
@pytest.mark.parametrize(
    ("text", "expected"),
    [("false", False), ("False", False), ("true", True), (" TRUE ", True)],
)
def test_flags_written_as_text_parse_as_booleans(configure, flag, text, expected) -> None:
    values = {**_COMPLETE, flag: text}
    if flag == "DEVELOPMENT_AUTH" and not expected:
        # Without development authentication, the run names its API key instead.
        values["API_KEY_ENV"] = "ARKHAI_PAYMENTS_API_KEY"
    configure(**values)
    config = payments.configured_payments(ready=lambda _url: True)
    assert getattr(config, flag.lower()) is expected


def test_development_auth_written_false_still_requires_an_api_key(configure) -> None:
    # `bool("false")` is true, which would waive the key for a non-development run.
    configure(**{**_COMPLETE, "DEVELOPMENT_AUTH": "false"})
    outcome = _outcome(ready=lambda _url: True)
    assert isinstance(outcome, Failed)
    assert "PAYMENTS.API_KEY_ENV is required without DEVELOPMENT_AUTH" in str(outcome)


@pytest.mark.parametrize("flag", ["LIVEMODE", "DEVELOPMENT_AUTH"])
def test_a_flag_that_is_not_a_boolean_fails(configure, flag) -> None:
    configure(**{**_COMPLETE, flag: "yes"})
    outcome = _outcome(ready=lambda _url: True)
    assert isinstance(outcome, Failed)
    assert f"PAYMENTS.{flag} must be true or false" in str(outcome)
