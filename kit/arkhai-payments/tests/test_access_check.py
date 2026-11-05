"""The payments access check's outcomes, each step it names, and its redaction."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    check_configured_payments_access,
    check_payments_access,
)

from payment_terms import PAYEE, SERVICE

# A public test-only key value that authenticates to nothing; never use it on a
# public network.
KEY = "sk_test_access_check_canary"
KEY_ENV = "SELLER_PAYMENTS_KEY"
URL = "https://127.0.0.1:9"


def section(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "enabled": True, "service_url": URL, "service_identity": SERVICE.identity,
        "fee_bps": 250, "api_key_env": KEY_ENV,
    }
    values.update(overrides)
    return values


def run(handler=None, *, config: Any = None, environment=None):
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if handler is None:
            return httpx.Response(200, json={"available": {}, "held": []})
        return handler(request)

    outcome = check_payments_access(
        ArkhaiPaymentsConfig(**section()) if config is None else config,
        PAYEE,
        environment={KEY_ENV: KEY} if environment is None else environment,
        transport=httpx.MockTransport(record),
    )
    return outcome, requests


def held_entry() -> dict[str, Any]:
    return {
        "address": f"hold:{'c' * 64}:0:until", "transaction": "c" * 64, "part": 0,
        "from": "11111111-1111-4111-8111-111111111111", "to": PAYEE, "asset": "USD/6",
        "balance": "1000000", "fee": {"bps": 250}, "until": "stop",
    }


def test_an_authenticated_balance_read_is_ok_with_the_accounts_assets_and_holds():
    outcome, requests = run(lambda request: httpx.Response(
        200, json={"available": {"USD/6": "0", "ETH/18": "1"}, "held": [held_entry()]}))
    assert [(r.method, r.url.path, r.headers["Authorization"]) for r in requests] == [
        ("GET", f"/balances/{PAYEE}", f"Bearer {KEY}")]
    assert outcome.ok and outcome.assets == ("ETH/18", "USD/6") and outcome.held == 1
    assert json.loads(outcome.json_line()) == {
        "check": "payments", "outcome": "ok", "service_url": URL, "account": PAYEE,
        "assets": ["ETH/18", "USD/6"], "held": 1,
    }
    assert "\n" not in outcome.json_line()


@pytest.mark.parametrize(
    "config, expected",
    [
        (None, "no [Settlement.arkhai_payments] section"),
        (section(service_url="ftp://payments.invalid"), "invalid: service_url"),
        (section(enabled=False), "not enabled"),
        (section(service_url=None), "service_url is not configured"),
        (section(api_key_env=None), "neither api_key nor api_key_env is configured"),
    ],
    ids=["no-section", "invalid-section", "disabled", "no-service-url", "no-key-form"],
)
def test_configuration_failures_name_the_configuration_step_before_any_request(config, expected):
    outcome = check_payments_access(
        config, PAYEE, environment={KEY_ENV: KEY},
        transport=httpx.MockTransport(lambda request: pytest.fail("no request expected")),
    )
    assert (outcome.outcome, outcome.step) == ("failed", "configuration")
    assert expected in (outcome.detail or "")


def test_a_missing_section_renders_without_a_service_url():
    outcome = check_payments_access(None, PAYEE, environment={})
    line = json.loads(outcome.json_line())
    assert line["step"] == "configuration" and "service_url" not in line


@pytest.mark.parametrize("environment", [{}, {KEY_ENV: "  "}, {KEY_ENV: "two\nlines"}],
                         ids=["unset", "blank", "multi-line"])
def test_an_unusable_key_variable_names_the_credential_step_and_the_variable(environment):
    outcome, requests = run(environment=environment)
    assert (outcome.step, requests) == ("credential", [])
    assert KEY_ENV in (outcome.detail or "")


def test_a_key_stated_in_the_secret_overlay_authenticates_with_no_variable_set():
    outcome, requests = run(
        config=ArkhaiPaymentsConfig(**section(api_key_env=None, api_key=KEY)), environment={},
    )
    assert outcome.ok
    assert [r.headers["Authorization"] for r in requests] == [f"Bearer {KEY}"]
    assert KEY not in outcome.json_line()


def test_an_untrusted_or_unreachable_service_names_the_transport_step():
    def untrusted(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    outcome, _ = run(untrusted)
    assert (outcome.outcome, outcome.step, outcome.service_url) == ("failed", "transport", URL)


def test_an_answer_outside_the_contract_names_the_transport_step():
    outcome, _ = run(lambda request: httpx.Response(200, content=b"<html>not payments</html>"))
    assert outcome.step == "transport" and "contract" in (outcome.detail or "")


def test_a_refusal_names_the_refused_step_and_the_services_code():
    outcome, _ = run(lambda request: httpx.Response(403, json={"error": "caller_not_authorized"}))
    assert (outcome.step, outcome.code) == ("refused", "caller_not_authorized")
    assert json.loads(outcome.json_line())["code"] == "caller_not_authorized"


def test_a_malformed_account_is_the_callers_error():
    with pytest.raises(ValueError):
        check_payments_access(ArkhaiPaymentsConfig(**section()), "seller", environment={})


def test_a_configuration_the_role_cannot_read_is_a_configuration_outcome_without_its_message():
    def unreadable():
        raise ValueError(f"cannot parse api_key = {KEY!r}")

    outcome = check_configured_payments_access(
        unreadable, PAYEE, environment={KEY_ENV: KEY},
        transport=httpx.MockTransport(lambda request: pytest.fail("no request expected")),
    )
    assert (outcome.outcome, outcome.step, outcome.service_url) == (
        "failed", "configuration", None)
    assert KEY not in outcome.json_line()


def test_the_configured_check_reads_the_section_the_role_serves_with():
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"available": {}, "held": []})

    outcome = check_configured_payments_access(
        section, PAYEE, environment={KEY_ENV: KEY}, transport=httpx.MockTransport(record),
    )
    assert outcome.ok and [r.url.path for r in requests] == [f"/balances/{PAYEE}"]


def test_the_configured_check_refuses_a_malformed_account_before_reading_configuration():
    with pytest.raises(ValueError):
        check_configured_payments_access(
            lambda: pytest.fail("configuration read before the account"), "seller",
            environment={},
        )


def _leaky_transport(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"proxy refused {request.headers['Authorization']} ({KEY})")


def _leaky_refusal(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, content=f"bad key {KEY}".encode())


@pytest.mark.parametrize(
    "handler, config",
    [
        (None, None),
        (_leaky_transport, None),
        (_leaky_refusal, None),
        (lambda request: httpx.Response(200, content=KEY.encode()), None),
        (None, section(api_key=KEY)),
        (None, section(api_key_env=KEY)),
        (None, section(service_url=f"https://user:{KEY}@payments.invalid")),
    ],
    ids=["ok", "transport", "refused", "protocol", "pasted-key", "key-as-variable",
         "key-in-url"],
)
def test_no_rendered_outcome_contains_the_api_key(handler, config):
    outcome, _ = run(handler, config=config)
    assert KEY not in outcome.json_line()
    assert KEY not in repr(outcome)
