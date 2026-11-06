"""`market-storefront check-payments` prints one outcome and exits by it.

Unit: the command module's own factories are its seams. ``payments_section``
stands in for the storefront's configuration, except in one case that reads the
storefront's settings as loaded, and ``payments_transport`` for the network under
the real payments client, so each case runs the real kit check over a mocked
HTTP boundary. Spec scenarios "The storefront can reach its payments service"
and "The storefront does not trust the payments origin", the latter as the
transport error httpx raises for an untrusted certificate, with no handshake.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from market_identity import Ed25519Signer

import market_storefront.cli as cli
from tests._settings_overrides import replaced_setting

# Public test-only values that authenticate to nothing; never use them on a
# public network.
SERVICE = Ed25519Signer(b"\x07" * 32)
KEY = "sk_test_vm_storefront_check_canary"
KEY_ENV = "VM_SELLER_PAYMENTS_KEY"
ACCOUNT = "00000000-0000-4000-8000-0000000000b2"
# A loopback origin: the client reads no proxy settings for one, so an ambient
# HTTPS_PROXY cannot route around the mocked transport.
URL = "https://127.0.0.1:8443"
NO_SECTION = object()


def section() -> dict[str, Any]:
    return {
        "enabled": True, "service_url": URL,
        "service_identity": SERVICE.identity.model_dump(mode="json"),
        "fee_bps": 250, "livemode": False, "api_key_env": KEY_ENV,
    }


def untrusted(request: httpx.Request) -> httpx.Response:
    # What httpx raises when the origin's certificate is not trusted; the text
    # carries the key to show it never reaches the output.
    raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] {KEY}", request=request)


def refusing(request: httpx.Request) -> httpx.Response:
    return httpx.Response(403, json={"code": "caller_not_authorized", "message": KEY})


def invoke(monkeypatch, runner, app, *, configured: Any = None, handler=None,
           environment: dict[str, str] | None = None, account: str = ACCOUNT):
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if handler is None:
            return httpx.Response(200, json={"available": {"USD/6": "0"}, "held": []})
        return handler(request)

    def read_section() -> Any:
        if isinstance(configured, Exception):
            raise configured
        if configured is NO_SECTION:
            return None
        return section() if configured is None else configured

    monkeypatch.setattr(cli, "payments_section", read_section)
    monkeypatch.setattr(cli, "payments_transport", lambda: httpx.MockTransport(answer))
    monkeypatch.delenv(KEY_ENV, raising=False)
    for name, value in ({KEY_ENV: KEY} if environment is None else environment).items():
        monkeypatch.setenv(name, value)
    result = runner.invoke(app, ["check-payments", "--account", account])
    return result, requests


def test_a_reachable_service_prints_ok_and_exits_zero(monkeypatch, runner, app):
    result, requests = invoke(monkeypatch, runner, app)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "check": "payments", "outcome": "ok", "service_url": URL, "account": ACCOUNT,
        "assets": ["USD/6"], "held": 0,
    }
    assert [(r.method, r.url.path, r.headers["Authorization"]) for r in requests] == [
        ("GET", f"/balances/{ACCOUNT}", f"Bearer {KEY}")
    ]


@pytest.mark.parametrize(
    "configured, environment, handler, step",
    [
        (NO_SECTION, None, None, "configuration"),
        (ValueError("unreadable"), None, None, "configuration"),
        (None, {}, None, "credential"),
        (None, None, untrusted, "transport"),
        (None, None, refusing, "refused"),
    ],
    ids=["no-section", "unreadable-configuration", "unset-key", "untrusted-origin",
         "refused"],
)
def test_each_failure_prints_its_step_and_exits_one(
    monkeypatch, runner, app, configured, environment, handler, step
):
    result, _ = invoke(monkeypatch, runner, app, configured=configured,
                       environment=environment, handler=handler)

    assert result.exit_code == 1, result.output
    outcome = json.loads(result.output)
    assert outcome["outcome"] == "failed" and outcome["step"] == step
    assert outcome["account"] == ACCOUNT
    assert KEY not in result.output


def test_the_section_is_read_from_the_storefronts_settlement_configuration(
    monkeypatch, runner, app
):
    """The real section reader, over the storefront's settings as loaded: only
    the network is replaced."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"available": {}, "held": []})

    monkeypatch.setattr(cli, "payments_transport", lambda: httpx.MockTransport(answer))
    monkeypatch.setenv(KEY_ENV, KEY)
    with replaced_setting("settlement", {"schema_version": 1,
                                         "priority": ["arkhai.payments.v1"],
                                         "arkhai_payments": section()}):
        result = runner.invoke(app, ["check-payments", "--account", ACCOUNT])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["service_url"] == URL
    assert [r.url.path for r in requests] == [f"/balances/{ACCOUNT}"]


def test_a_malformed_account_is_a_usage_error_before_any_request(monkeypatch, runner, app):
    result, requests = invoke(monkeypatch, runner, app, account="not-an-account")

    assert result.exit_code == 2
    assert "--account" in result.output
    assert requests == []
