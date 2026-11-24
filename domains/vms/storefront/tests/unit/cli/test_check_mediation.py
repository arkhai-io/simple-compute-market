"""`market-storefront check-mediation` prints one outcome and exits by it.

Unit: the command module's own factories are its seams. ``dispute_credentials``
stands in for the storefront's configuration, except in one case that reads the
storefront's settings as loaded, and ``mediation_transport`` for the network
under the real mediation client, so each case runs the real kit check over a
mocked HTTP boundary. Spec scenarios of "A storefront checks its mediation
configuration from its own container": access (an empty listing; a full one is
the kit's unit case), no credential for the origin, an unresolvable token, an
untrusted authority (the transport error httpx raises for an untrusted
certificate, with no handshake), and a refused token. A CA bundle that cannot be
loaded is the kit's unit case.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_deal_lifecycle.configuration import DisputeCredential

import market_storefront.cli as cli
from tests._settings_overrides import replaced_setting

# Public test-only values that authenticate to nothing; never use them on a
# public network.
TOKEN = "vm-storefront-mediation-check-canary"
TOKEN_ENV = "VM_SELLER_MEDIATION_TOKEN"
# Nothing listens here: every case injects the transport, under which httpx
# reads no proxy setting, so no request leaves the process.
ORIGIN = "https://127.0.0.1:8443"
EMPTY_LISTING = {"cases": [], "next_after": "", "has_more": False}


def entry() -> dict[str, Any]:
    """The credential as the storefront's secret overlay would state it."""
    authority = MediationContractFake().authority
    return {
        "interface": authority["interface"], "origin": ORIGIN,
        "account": authority["account"], "record_key": authority["record_key"],
        "api_key_env": TOKEN_ENV,
    }


def untrusted(request: httpx.Request) -> httpx.Response:
    # What httpx raises when the origin's certificate is not trusted; the text
    # carries the token to show it never reaches the output.
    raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] {TOKEN}", request=request)


def refusing(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"code": "authentication_required", "message": TOKEN})


def invoke(monkeypatch, runner, app, *, configured: Any = None, handler=None,
           environment: dict[str, str] | None = None, origin: str = ORIGIN):
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if handler is None:
            return httpx.Response(200, json=EMPTY_LISTING)
        return handler(request)

    def read_credentials() -> list[DisputeCredential]:
        if isinstance(configured, Exception):
            raise configured
        entries = [entry()] if configured is None else configured
        return [DisputeCredential.model_validate(item) for item in entries]

    monkeypatch.setattr(cli, "dispute_credentials", read_credentials)
    monkeypatch.setattr(cli, "mediation_transport", lambda: httpx.MockTransport(answer))
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    for name, value in ({TOKEN_ENV: TOKEN} if environment is None else environment).items():
        monkeypatch.setenv(name, value)
    result = runner.invoke(app, ["check-mediation", "--origin", origin])
    return result, requests


def test_a_reachable_authority_prints_ok_and_exits_zero(monkeypatch, runner, app):
    result, requests = invoke(monkeypatch, runner, app)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"check": "mediation", "outcome": "ok", "origin": ORIGIN}
    assert [(r.method, r.url.path, r.headers["Authorization"]) for r in requests] == [
        ("GET", "/respondent", f"Bearer {TOKEN}")
    ]


@pytest.mark.parametrize(
    "configured, environment, handler, step",
    [
        ([], None, None, "configuration"),
        (ValueError("unreadable"), None, None, "configuration"),
        (None, {}, None, "credential"),
        (None, None, untrusted, "transport"),
        (None, None, refusing, "refused"),
    ],
    ids=["no-credential", "unreadable-configuration", "unset-token", "untrusted-origin",
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
    assert outcome["origin"] == ORIGIN
    if step == "refused":
        assert outcome["code"] == "authentication_required"
    assert TOKEN not in result.output


def test_the_credentials_are_read_from_the_storefronts_configuration(monkeypatch, runner, app):
    """The real credential reader, over the storefront's settings as loaded:
    only the network is replaced."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=EMPTY_LISTING)

    monkeypatch.setattr(cli, "mediation_transport", lambda: httpx.MockTransport(answer))
    stated = {key: value for key, value in entry().items() if key != "api_key_env"}
    with replaced_setting("disputecredential", [stated | {"api_key": TOKEN}]):
        result = runner.invoke(app, ["check-mediation", "--origin", ORIGIN])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["origin"] == ORIGIN
    assert [(r.url.path, r.headers["Authorization"]) for r in requests] == [
        ("/respondent", f"Bearer {TOKEN}")
    ]


def test_a_malformed_origin_is_a_usage_error_before_any_request(monkeypatch, runner, app):
    result, requests = invoke(monkeypatch, runner, app, origin="mediation-double:8443")

    assert result.exit_code == 2
    assert "--origin" in result.output
    assert requests == []
