"""The shared payments helper blocks only an absent or unready external target.

A run that configures no payments target has its payment scenarios blocked.
Once a target is configured, the run is expected to supply everything else, and
a missing setting fails rather than hiding a broken configuration behind a skip.
A lane's own target, marked LANE_OWNED, fails when it is not ready. Every value
below is a development fixture, never used on any network.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.e2e.roles.helpers import payments

# The payments lane double's CA, a public development certificate.
_LANE_CA = Path(__file__).resolve().parents[3] / "tools/payments-lane-double/tls/lane-ca.pem"

Failed = pytest.fail.Exception
Skipped = pytest.skip.Exception

_COMPLETE = {
    "SERVICE_URL": "http://127.0.0.1:9",
    "SERVICE_IDENTITY": "A" * 43,
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


def test_an_unready_lane_owned_target_fails_naming_it(configure) -> None:
    configure(**_COMPLETE, LANE_OWNED="true")
    outcome = _outcome(ready=lambda _url: False)
    assert isinstance(outcome, Failed)
    assert "the lane's own payments service at http://127.0.0.1:9 is not ready" in str(outcome)


def test_a_ready_lane_owned_target_yields_its_policy(configure) -> None:
    configure(**_COMPLETE, LANE_OWNED=True)
    config = payments.configured_payments(ready=lambda _url: True)
    assert config.service_url == "http://127.0.0.1:9"


def test_a_lane_owned_run_without_a_target_fails(configure) -> None:
    configure(LANE_OWNED=True)
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Failed)
    assert "PAYMENTS.LANE_OWNED is set but PAYMENTS.SERVICE_URL is not configured" in str(outcome)


def test_an_unready_target_marked_external_still_blocks(configure) -> None:
    configure(**_COMPLETE, LANE_OWNED="false")
    outcome = _outcome(ready=lambda _url: False)
    assert isinstance(outcome, Skipped)
    assert "blocked: payments service at http://127.0.0.1:9 is not ready" in str(outcome)


class _Probe:
    """Records the request the readiness probe makes and answers it."""

    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _healthy() -> httpx.Response:
    return httpx.Response(200, json={"status": "ok"})


def test_the_probe_trusts_the_ca_ssl_cert_file_names_and_no_proxy() -> None:
    probe = _Probe(_healthy())
    assert payments.target_ready(
        "https://payments-double:8443", get=probe, environ={"SSL_CERT_FILE": str(_LANE_CA)},
    )
    ((url, kwargs),) = probe.calls
    assert url == "https://payments-double:8443/health"
    assert kwargs["trust_env"] is False
    context = kwargs["verify"]
    assert isinstance(context, ssl.SSLContext)
    lane_ca = ssl.create_default_context(cafile=str(_LANE_CA)).get_ca_certs()
    assert context.get_ca_certs() == lane_ca and lane_ca


def test_without_ssl_cert_file_the_probe_keeps_default_verification() -> None:
    probe = _Probe(_healthy())
    assert payments.target_ready("https://payments.example", get=probe, environ={})
    ((_, kwargs),) = probe.calls
    assert kwargs["verify"] is True and kwargs["trust_env"] is False


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"status": "ok"}),
        httpx.Response(200, json={"status": "starting"}),
        httpx.Response(200, text="not json"),
        httpx.ConnectError("certificate verify failed"),
    ],
)
def test_the_probe_reports_an_unhealthy_or_unreachable_target_unready(response) -> None:
    assert not payments.target_ready("https://payments-double:8443", get=_Probe(response), environ={})


@pytest.mark.parametrize("bundle", ["missing", "malformed"])
def test_a_trust_bundle_that_cannot_be_loaded_leaves_the_target_unready(tmp_path, bundle) -> None:
    path = tmp_path / "lane-ca.pem"
    if bundle == "malformed":
        path.write_text("-----BEGIN CERTIFICATE-----\nnot a certificate\n", "utf-8")
    probe = _Probe(_healthy())
    assert not payments.target_ready(
        "https://payments-double:8443", get=probe, environ={"SSL_CERT_FILE": str(path)},
    )
    assert probe.calls == []


@pytest.mark.parametrize("flag", ["LIVEMODE", "DEVELOPMENT_AUTH", "LANE_OWNED"])
def test_a_flag_that_is_not_a_boolean_fails(configure, flag) -> None:
    configure(**{**_COMPLETE, flag: "yes"})
    outcome = _outcome(ready=lambda _url: True)
    assert isinstance(outcome, Failed)
    assert f"PAYMENTS.{flag} must be true or false" in str(outcome)
