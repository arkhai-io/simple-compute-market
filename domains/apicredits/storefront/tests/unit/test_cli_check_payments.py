"""`apicredits-storefront check-payments` prints one outcome and exits by it.

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
from typer.testing import CliRunner

import apicredits_storefront.cli as cli
from tests._settings_overrides import replaced_setting

# Public test-only values that authenticate to nothing; never use them on a
# public network.
SERVICE = Ed25519Signer(b"\x07" * 32)
KEY = "sk_test_apicredits_storefront_check_canary"
KEY_ENV = "APICREDITS_SELLER_PAYMENTS_KEY"
ACCOUNT = "00000000-0000-4000-8000-0000000000b2"
# A loopback origin: the client reads no proxy settings for one, so an ambient
# HTTPS_PROXY cannot route around the mocked transport.
URL = "https://127.0.0.1:8443"
NO_SECTION = object()

runner = CliRunner()


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


def invoke(monkeypatch, *, configured: Any = None, handler=None, key: str | None = KEY):
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if handler is None:
            return httpx.Response(200, json={"available": {"USD/6": "0"}, "held": []})
        return handler(request)

    def read_section() -> Any:
        if isinstance(configured, Exception):
            raise configured
        return None if configured is NO_SECTION else section()

    monkeypatch.setattr(cli, "payments_section", read_section)
    monkeypatch.setattr(cli, "payments_transport", lambda: httpx.MockTransport(answer))
    monkeypatch.delenv(KEY_ENV, raising=False)
    if key is not None:
        monkeypatch.setenv(KEY_ENV, key)
    return runner.invoke(cli.app, ["check-payments", "--account", ACCOUNT]), requests


def test_a_reachable_service_prints_ok_and_exits_zero(monkeypatch):
    result, requests = invoke(monkeypatch)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "check": "payments", "outcome": "ok", "service_url": URL, "account": ACCOUNT,
        "assets": ["USD/6"], "held": 0,
    }
    assert [(r.url.path, r.headers["Authorization"]) for r in requests] == [
        (f"/balances/{ACCOUNT}", f"Bearer {KEY}")
    ]


def test_the_section_is_read_from_the_storefronts_settlement_configuration(monkeypatch):
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
        result = runner.invoke(cli.app, ["check-payments", "--account", ACCOUNT])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["service_url"] == URL
    assert [r.url.path for r in requests] == [f"/balances/{ACCOUNT}"]


@pytest.mark.parametrize(
    "configured, key, handler, step",
    [
        (NO_SECTION, KEY, None, "configuration"),
        (ValueError("unreadable"), KEY, None, "configuration"),
        (None, None, None, "credential"),
        (None, KEY, untrusted, "transport"),
    ],
    ids=["no-section", "unreadable-configuration", "unset-key", "untrusted-origin"],
)
def test_each_failure_prints_its_step_and_exits_one(monkeypatch, configured, key, handler, step):
    result, _ = invoke(monkeypatch, configured=configured, key=key, handler=handler)

    assert result.exit_code == 1, result.output
    outcome = json.loads(result.output)
    assert outcome["outcome"] == "failed" and outcome["step"] == step
    assert KEY not in result.output
