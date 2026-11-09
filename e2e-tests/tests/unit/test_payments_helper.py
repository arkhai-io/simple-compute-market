"""The shared payments helper blocks only an absent or unready external target.

A run that configures no payments target has its payment scenarios blocked.
Once a target is configured, the run is expected to supply everything else, and
a missing setting fails rather than hiding a broken configuration behind a skip.
A lane's own target, marked LANE_OWNED, fails when it is not ready. Every value
below is a development fixture, never used on any network.
"""

from __future__ import annotations

import os
import ssl
import tomllib
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import pytest
from market_identity import IdentityScheme

from tests.e2e.roles.buyer_cli import create_profiled_buyer_cli
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
        values["BUYER_API_KEY"] = "payments-helper-test-buyer-key"
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


def test_the_probe_trusts_the_configured_bundle_alone_and_no_proxy() -> None:
    probe = _Probe(_healthy())
    assert payments.target_ready(
        "https://payments-double:8443", ca_bundle=str(_LANE_CA), get=probe,
    )
    ((url, kwargs),) = probe.calls
    assert url == "https://payments-double:8443/health"
    assert kwargs["trust_env"] is False
    context = kwargs["verify"]
    assert isinstance(context, ssl.SSLContext)
    lane_ca = ssl.create_default_context(cafile=str(_LANE_CA)).get_ca_certs()
    assert context.get_ca_certs() == lane_ca and lane_ca


def test_without_a_bundle_the_probe_keeps_default_verification(monkeypatch) -> None:
    # The process's SSL_CERT_FILE is not the probe's configuration.
    monkeypatch.setenv("SSL_CERT_FILE", str(_LANE_CA))
    probe = _Probe(_healthy())
    assert payments.target_ready("https://payments.example", get=probe)
    ((_, kwargs),) = probe.calls
    assert kwargs["verify"] is True and kwargs["trust_env"] is False


def test_the_default_readiness_probe_trusts_the_configured_bundle(configure, monkeypatch) -> None:
    asked: list[tuple[str, str | None]] = []

    def probe(url: str, *, ca_bundle: str | None = None) -> bool:
        asked.append((url, ca_bundle))
        return True

    monkeypatch.setattr(payments, "target_ready", probe)
    configure(**_COMPLETE, CA_BUNDLE_PATH=str(_LANE_CA))
    config = payments.configured_payments()
    assert config.ca_bundle_path == str(_LANE_CA)
    assert asked == [("http://127.0.0.1:9", str(_LANE_CA))]


@pytest.mark.parametrize("bundle", ["lane CA", "missing"])
def test_a_lane_owned_target_is_ready_only_under_a_bundle_that_loads(
    configure, monkeypatch, tmp_path, bundle,
) -> None:
    """The default probe, answering healthy, over the configured bundle: the
    lane CA lets the target be ready, and a missing bundle fails it by name."""
    path = _LANE_CA if bundle == "lane CA" else tmp_path / "missing.pem"
    probe = _Probe(_healthy())
    monkeypatch.setattr(payments, "target_ready", partial(payments.target_ready, get=probe))
    configure(**_COMPLETE, LANE_OWNED=True, CA_BUNDLE_PATH=str(path))
    if bundle == "lane CA":
        assert payments.configured_payments().ca_bundle_path == str(_LANE_CA)
        assert len(probe.calls) == 1
        return
    outcome = _outcome()
    assert isinstance(outcome, Failed)
    assert "the lane's own payments service at http://127.0.0.1:9 is not ready" in str(outcome)
    assert probe.calls == []


# The buyer's bearer key, a development fixture value.
_BUYER_KEY = "payments-helper-test-buyer-key"
_KEYED = {**_COMPLETE, "DEVELOPMENT_AUTH": False, "API_KEY_ENV": "PAYMENTS_BUYER_API_KEY",
          "BUYER_API_KEY": _BUYER_KEY}


def test_the_buyer_key_is_handed_over_under_the_variable_the_configuration_names(
    configure, monkeypatch,
) -> None:
    monkeypatch.delenv("PAYMENTS_BUYER_API_KEY", raising=False)
    configure(**_KEYED)
    config = payments.configured_payments(ready=lambda _url: True)
    assert payments.buyer_payments_environment(config) == {"PAYMENTS_BUYER_API_KEY": _BUYER_KEY}
    # Handed to the buyer, never written into the runner's own environment.
    assert "PAYMENTS_BUYER_API_KEY" not in os.environ
    assert _BUYER_KEY not in os.environ.values()


def test_the_buyer_key_reaches_the_market_process_environment(configure, tmp_path) -> None:
    configure(**_KEYED)
    config = payments.configured_payments(ready=lambda _url: True)
    cli = create_profiled_buyer_cli(
        binary=tmp_path / "market",
        base=tmp_path,
        domain_identity="api_credits.v1",
        marketplace_scheme=IdentityScheme.ED25519,
        marketplace_credential="sbGxsbGxsbGxsbGxsbGxsbGxsbGxsbGxsbGxsbGxsbE",
        registries=("http://registry:8080",),
        credential_variable="ARKHAI_E2E_PAYMENT_BUYER_MARKETPLACE_CREDENTIAL",
        credential_environment=payments.buyer_payments_environment(config),
        toml_sections=payments.payment_config_toml(config),
    )
    assert cli.credential_env["PAYMENTS_BUYER_API_KEY"] == _BUYER_KEY
    assert set(cli.credential_env) == {
        "PAYMENTS_BUYER_API_KEY", "ARKHAI_E2E_PAYMENT_BUYER_MARKETPLACE_CREDENTIAL",
    }


@pytest.mark.parametrize("values", [
    {"DEVELOPMENT_AUTH": True, "API_KEY_ENV": ""},
])
def test_no_key_is_handed_over_without_one_or_with_development_authentication(
    configure, values,
) -> None:
    configure(**{**_KEYED, **values})
    config = payments.configured_payments(ready=lambda _url: True)
    assert payments.buyer_payments_environment(config) == {}


def test_an_in_process_buyer_client_authenticates_with_the_handed_over_key(
    configure, monkeypatch,
) -> None:
    monkeypatch.delenv("PAYMENTS_BUYER_API_KEY", raising=False)
    # A loopback origin, so no ambient proxy is mounted ahead of the mock.
    configure(**{**_KEYED, "SERVICE_URL": "https://127.0.0.1"})
    config = payments.configured_payments(ready=lambda _url: True)
    seen: list[str | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"available": {}, "held": []})

    account = _COMPLETE["BUYER_ACCOUNT"]
    with payments.buyer_payments_client(
        config, account, transport=httpx.MockTransport(answer)
    ) as client:
        client.get_balance(account)
    assert seen == [f"Bearer {_BUYER_KEY}"]


def test_the_buyer_configuration_trusts_the_configured_bundle(configure) -> None:
    configure(**_KEYED, CA_BUNDLE_PATH=str(_LANE_CA))
    config = payments.configured_payments(ready=lambda _url: True)
    section = tomllib.loads("\n".join(payments.payment_config_toml(config)))
    assert section["Settlement"]["arkhai_payments"]["ca_bundle_path"] == str(_LANE_CA)
    assert section["Settlement"]["arkhai_payments"]["api_key_env"] == "PAYMENTS_BUYER_API_KEY"


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
    assert not payments.target_ready("https://payments-double:8443", get=_Probe(response))


@pytest.mark.parametrize("bundle", ["missing", "malformed"])
def test_a_trust_bundle_that_cannot_be_loaded_leaves_the_target_unready(tmp_path, bundle) -> None:
    path = tmp_path / "lane-ca.pem"
    if bundle == "malformed":
        path.write_text("-----BEGIN CERTIFICATE-----\nnot a certificate\n", "utf-8")
    probe = _Probe(_healthy())
    assert not payments.target_ready(
        "https://payments-double:8443", ca_bundle=str(path), get=probe,
    )
    assert probe.calls == []


@pytest.mark.parametrize("flag", ["LIVEMODE", "DEVELOPMENT_AUTH", "LANE_OWNED"])
def test_a_flag_that_is_not_a_boolean_fails(configure, flag) -> None:
    configure(**{**_COMPLETE, flag: "yes"})
    outcome = _outcome(ready=lambda _url: True)
    assert isinstance(outcome, Failed)
    assert f"PAYMENTS.{flag} must be true or false" in str(outcome)


@pytest.mark.parametrize("token", [None, "", " ", "public-test-token\n", "public\rtest-token"])
def test_an_unusable_buyer_token_fails_before_readiness_without_exposing_it(configure, token) -> None:
    configure(**{**_KEYED, "BUYER_API_KEY": token})
    outcome = _outcome(ready=_never_asked)
    assert isinstance(outcome, Failed)
    assert "PAYMENTS.BUYER_API_KEY" in str(outcome)
    assert "public-test-token" not in str(outcome)
    assert "public\rtest-token" not in str(outcome)


def test_development_authentication_needs_no_buyer_token(configure) -> None:
    configure(**{**_COMPLETE, "BUYER_API_KEY": "", "API_KEY_ENV": ""})
    config = payments.configured_payments(ready=lambda _url: True)
    assert payments.buyer_payments_environment(config) == {}
