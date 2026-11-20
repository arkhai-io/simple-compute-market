"""The sample app's time control, and the gate signing at the time it sets.

The real app, driven in process: the control through the lane doubles' typed
``ControlClient``, the metered endpoint through httpx. The credits service is a
stand-in at an instant of its own, which verifies each of the gate's signed calls
as the service does — the request's freshness against its own instant included —
and signs its answers; it stands for a credits service the lane sets alike. The
real service against the same signing is its own suite's
(``domains/apicredits/service``, the injected-time grant test).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import injected_time
import pytest
from fastapi.testclient import TestClient
from injected_time import InjectedTime, InvalidTimeSource, WallTime

from arkhai_api_gate import GateConfig, TokenGate, TokensClient
from arkhai_api_gate.signing import AuthoritySigning, build_trusted_authorities
from apicredits_sample_app.app import AUTHORITY_LABEL, configured_app, create_app
from lane_double_controls import ControlClient, ControlError, TimeView
from market_identity import (
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    VerificationCode,
    canonical_body_hash,
    sign_response,
    verify_request,
)

T = 1_794_821_400
HOUR = 3_600
# Public test seeds and tokens, never for a public network.
AUTHORITY = Ed25519Signer(b"sample-app-authority-seed-32byte")
GATED_APP = Ed25519Signer(b"sample-app-gated-app-seed-32byte")
CONTROL_TOKEN = "sample-app-suite-control-token"
KEY_ID = "ak-1"
KEY_SECRET = f"{KEY_ID}.secret"

_OPERATIONS = {"verify": "credits_key_verify", "consume": "credits_key_consume"}


class StandInAuthority:
    """A credits service at its own time: verifies, answers and signs as the service does.

    It holds one key, ``KEY_ID``, and answers any other ``key_not_found``.
    """

    def __init__(self, time: InjectedTime | WallTime, balance: int) -> None:
        self.time = time
        self.balance = balance
        self.verdicts: list[tuple[str, VerificationCode]] = []
        #: The status of each answer, in order.
        self.answered: list[int] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        key_id, action = request.url.path.removeprefix("/api/v1/keys/").split("/")
        operation = _OPERATIONS[action]
        body = json.loads(request.content)
        headers = request.headers
        verdict = verify_request(
            AuthenticatedRequest(
                role=headers["X-Market-Role"],
                principal=Identity(scheme=headers["X-Market-Identity-Scheme"],
                                   identifier=headers["X-Market-Identity-Identifier"]),
                method=request.method, operation=operation, resource=key_id,
                request_id=headers["X-Market-Request-ID"],
                timestamp=int(headers["X-Market-Timestamp"]),
                body_hash=canonical_body_hash(body),
                proof=SignatureProof(scheme=headers["X-Market-Identity-Scheme"],
                                     value=headers["X-Market-Signature"])),
            body=body, now=self.time.now(), max_skew=300, expected_role="service",
            expected_method=request.method, expected_operation=operation,
            expected_resource=key_id,
            expected_principals=TrustedIdentitySet(identities=(GATED_APP.identity,)))
        self.verdicts.append((action, verdict.code))
        if verdict.code != VerificationCode.VERIFIED:
            return self._signed(request, operation, key_id, 401,
                                {"error": "unauthenticated"})
        if key_id != KEY_ID:
            return self._signed(request, operation, key_id, 404, {"error": "key_not_found"})
        if action == "verify":
            return self._signed(request, operation, key_id, 200,
                                {"valid": True, "status": "active", "balance": self.balance})
        self.balance -= body["amount"]
        return self._signed(request, operation, key_id, 200,
                            {"ok": True, "consumed": body["amount"], "balance": self.balance})

    def _signed(self, request: httpx.Request, operation: str, resource: str, status: int,
                body: dict[str, Any]) -> httpx.Response:
        self.answered.append(status)
        signed = sign_response(signer=AUTHORITY, envelope=ResponseEnvelope(
            role="service", principal=AUTHORITY.identity, method=request.method,
            operation=operation, resource=resource,
            request_id=request.headers["X-Market-Request-ID"], timestamp=self.time.now(),
            status=status, body_hash=canonical_body_hash(body)))
        return httpx.Response(status, json=body, headers={
            "X-Market-Signature-Version": signed.protocol,
            "X-Market-Identity-Scheme": signed.principal.scheme.value,
            "X-Market-Identity-Identifier": signed.principal.identifier,
            "X-Market-Role": signed.role,
            "X-Market-Request-ID": signed.request_id,
            "X-Market-Timestamp": str(signed.timestamp),
            "X-Market-Signature": signed.proof.value,
        })


class Served:
    """The app over the process source, its gate signing to a stand-in authority."""

    def __init__(self, source: InjectedTime | WallTime, authority: StandInAuthority) -> None:
        self.authority = authority
        config = GateConfig(service_url="http://credits", authority_label=AUTHORITY_LABEL)
        self.gate_http = httpx.AsyncClient(transport=httpx.MockTransport(authority.handle))
        gate = TokenGate(config, TokensClient(
            service_url=config.service_url, http=self.gate_http,
            signing=AuthoritySigning(
                signer=GATED_APP,
                expected_authorities=build_trusted_authorities([{
                    "scheme": AUTHORITY.identity.scheme.value,
                    "identifier": AUTHORITY.identity.identifier}]),
                authority_label=AUTHORITY_LABEL)))
        self.app = create_app(config, gate=gate, source=source, control_token=CONTROL_TOKEN)
        self.http = TestClient(self.app, base_url="http://sample-app")

    def controls(self, token: str = CONTROL_TOKEN) -> ControlClient:
        def forward(request: httpx.Request) -> httpx.Response:
            answer = self.http.request(request.method, str(request.url),
                                       headers=request.headers, content=request.content)
            return httpx.Response(answer.status_code, headers=answer.headers,
                                  content=answer.content)
        return ControlClient("http://sample-app", token=token,
                             transport=httpx.MockTransport(forward))

    def forecast(self) -> httpx.Response:
        return self.http.get("/api/forecast", headers={"Authorization": f"Bearer {KEY_SECRET}"})


@pytest.fixture
def wall() -> Iterator[WallTime]:
    """The process's source, wall time, which the gate then signs by."""
    before = injected_time.installed()
    held = injected_time.install(WallTime())
    assert isinstance(held, WallTime)
    yield held
    injected_time.install(before)


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process's source, injected at ``T``: the gate signs by the installed source."""
    before = injected_time.installed()
    held = injected_time.install(InjectedTime(start=T))
    assert isinstance(held, InjectedTime)
    yield held
    injected_time.install(before)


def test_the_control_sets_the_apps_time_and_is_neither_charged_nor_refused_by_the_gate(
        source: InjectedTime) -> None:
    served = Served(source, StandInAuthority(InjectedTime(start=T), balance=5))
    with served.http, served.controls() as controls:
        assert controls.status().time == TimeView(source="injected", now=T)

        assert controls.set_time(T + HOUR) == TimeView(source="injected", now=T + HOUR)

        assert controls.status().time.now == T + HOUR
    assert source.now() == T + HOUR
    # Neither control call reached the credits service: nothing verified, nothing spent.
    assert (served.authority.verdicts, served.authority.balance) == ([], 5)


@pytest.mark.parametrize(("now", "expected"), [
    (T - 1, (409, "time_moves_forward")),
    (True, (422, "invalid_time")),
])
def test_a_refused_setting_changes_nothing(source: InjectedTime, now: int,
                                           expected: tuple[int, str]) -> None:
    served = Served(source, StandInAuthority(InjectedTime(start=T), balance=5))
    with served.http, served.controls() as controls:
        with pytest.raises(ControlError) as refused:
            controls.set_time(now)

    assert (refused.value.status, refused.value.code) == expected
    assert source.now() == T


def test_a_control_call_with_a_wrong_control_token_is_refused(source: InjectedTime) -> None:
    served = Served(source, StandInAuthority(InjectedTime(start=T), balance=5))
    # A public test value, never for a public network.
    with served.http, served.controls("not-the-control-token") as controls:
        with pytest.raises(ControlError) as refused:
            controls.set_time(T + HOUR)

    assert (refused.value.status, refused.value.code) == (401, "authentication_required")
    assert source.now() == T


def test_metered_calls_continue_after_an_advance_set_alike_at_the_credits_service(
        source: InjectedTime) -> None:
    authority = StandInAuthority(InjectedTime(start=T + HOUR), balance=5)
    served = Served(source, authority)
    with served.http, served.controls() as controls:
        # The credits service is an hour ahead of the app: the gate's signed
        # verification, stamped at the app's instant, is refused for its skew,
        # and the refusal, stamped an hour ahead, is no answer the gate can
        # authenticate, so the gate closes.
        assert served.forecast().status_code == 503
        assert authority.verdicts == [("verify", VerificationCode.TIMESTAMP_SKEW)]

        controls.set_time(T + HOUR)
        answer = served.forecast()

    assert answer.status_code == 200
    assert authority.verdicts[1:] == [("verify", VerificationCode.VERIFIED),
                                      ("consume", VerificationCode.VERIFIED)]
    assert authority.balance == 4


def test_a_wall_time_app_passes_the_control_path_to_the_gate(wall: WallTime) -> None:
    authority = StandInAuthority(wall, balance=5)
    served = Served(wall, authority)
    with served.http, served.controls() as controls:
        with pytest.raises(ControlError) as refused:
            controls.set_time(T)

    # The gate, not a control, answered: its refusal is no control error.
    assert (refused.value.status, refused.value.code) == (401, "unexpected_response")
    # The gate took the control token for an API key and asked the credits
    # service, which verified the call and knows no such key; nothing was spent.
    assert authority.verdicts == [("verify", VerificationCode.VERIFIED)]
    assert authority.answered == [404]
    assert authority.balance == 5


def test_an_injected_app_without_a_control_token_refuses_to_start(
        source: InjectedTime) -> None:
    with pytest.raises(ValueError, match="APICREDITS_SAMPLE_APP_CONTROL_TOKEN"):
        create_app(GateConfig(service_url="http://credits", authority_label=AUTHORITY_LABEL), source=source)


def test_the_configured_app_installs_and_announces_injected_time(
        source: InjectedTime, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("APICREDITS_SAMPLE_APP_TIME_SOURCE", "injected")
    monkeypatch.setenv("APICREDITS_SAMPLE_APP_CONTROL_TOKEN", CONTROL_TOKEN)

    with caplog.at_level(logging.INFO):
        app = configured_app()

    installed = injected_time.installed()
    assert isinstance(installed, InjectedTime) and installed is not source
    assert [record.getMessage() for record in caplog.records] == [
        f"APICREDITS_SAMPLE_APP_TIME_SOURCE is injected: the app holds {installed.now()} "
        "until its time control sets it"]
    assert any(getattr(route, "path", None) == "/test/time" for route in app.routes)


def test_the_configured_app_on_wall_time_serves_no_time_control(
        wall: WallTime, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("APICREDITS_SAMPLE_APP_TIME_SOURCE", raising=False)
    monkeypatch.delenv("APICREDITS_SAMPLE_APP_CONTROL_TOKEN", raising=False)

    with caplog.at_level(logging.INFO):
        app = configured_app()

    assert isinstance(injected_time.installed(), WallTime)
    assert caplog.records == []
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/forecast" in paths
    assert not paths & {"/test/time", "/test/status"}


def test_a_misspelled_time_source_refuses_the_start_naming_the_setting(
        source: InjectedTime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APICREDITS_SAMPLE_APP_TIME_SOURCE", "injectd")

    with pytest.raises(InvalidTimeSource) as refused:
        configured_app()

    assert str(refused.value) == (
        "APICREDITS_SAMPLE_APP_TIME_SOURCE is \"wall\" or \"injected\", not 'injectd'")
    assert injected_time.installed() is source
