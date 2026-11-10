"""The typed control client against a double's control surface, through httpx.

A small stand-in answers only the control routes' declared methods and paths,
recording each request and answering what the test programs; any other request
is a 404 with no control body. Each client method's request is read back and held
to the literal method, path and body its route has, so a method wired to the wrong
declaration fails, and each answer and refusal is parsed into the typed models.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, get_args

import httpx
import pytest
from loopback import serving

from lane_double_controls import routes
from lane_double_controls.client import ControlClient
from lane_double_controls.models import ControlCode, ControlError, Rule, Ruling

_TOKEN = "control-token-for-tests"
_TRANSACTION = "a" * 64
_CASE = {"case_ref": "case-1", "transaction": _TRANSACTION, "agreement": "b" * 64,
         "state": "open", "filer": "payee", "kind": "delivery_end", "cause": "payee"}
_RULE = Rule(rule_id="r.1", match={}, unavailable=True)
_RULE_VIEW = {"rule": _RULE.model_dump(mode="json", exclude_none=True),
              "matched": 0, "waiting": 0}
_CLOCK = {"perceived_now": 1_800_000_060, "offset_seconds": 60}
_RULING = Ruling(basis="operator", delivery_end=False,
                 effects=[{"kind": "reverse", "part": 0, "amount": "100"}], close=True)


class _Surface:
    """Answers the declared control routes with a programmed status and body."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: tuple[int, Any] = (200, {})
        self._declared = [
            (route.method, re.compile(re.sub(r"\{[a-z_]+\}", "[^/]+", route.path) + "$"))
            for route in routes.ROUTES]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.raw_path.split(b"?")[0].decode()
        if not any(method == request.method and pattern.match(path)
                   for method, pattern in self._declared):
            return httpx.Response(404, text="no such route")
        status, body = self.answer
        return httpx.Response(status) if status == 204 else httpx.Response(status, json=body)

    def last_body(self) -> Any:
        content = self.requests[-1].content
        return json.loads(content) if content else None


@pytest.fixture
def surface() -> _Surface:
    return _Surface()


@pytest.fixture
def client(surface: _Surface) -> Iterator[ControlClient]:
    with ControlClient("https://mediation-double:8443", token=_TOKEN,
                       transport=httpx.MockTransport(surface.handle)) as control:
        yield control


# Each client method, the literal method, path, query and body it must send, and
# the answer the stand-in gives it.
_CALLS: list[tuple[str, Callable[[ControlClient], Any], str, str, dict[str, str], Any,
                   tuple[int, Any]]] = [
    ("install_rule", lambda c: c.install_rule(_RULE), "POST", "/test/rules", {},
     {"rule_id": "r.1", "match": {}, "unavailable": True, "pause_before_effects": False},
     (201, _RULE_VIEW)),
    ("rules", lambda c: c.rules(), "GET", "/test/rules", {}, None, (200, {"rules": []})),
    ("delete_rule", lambda c: c.delete_rule("r.1"), "DELETE", "/test/rules/r.1", {}, None,
     (204, None)),
    ("resume_rule", lambda c: c.resume_rule("r.1"), "POST", "/test/rules/r.1/resume", {},
     None, (200, _RULE_VIEW)),
    ("advance_clock", lambda c: c.advance_clock(60), "POST", "/test/clock/advance", {},
     {"seconds": 60}, (200, _CLOCK)),
    ("reset_clock", lambda c: c.reset_clock(), "POST", "/test/clock/reset", {}, None,
     (200, {"perceived_now": 1_800_000_000, "offset_seconds": 0})),
    ("status", lambda c: c.status(), "GET", "/test/status", {}, None,
     (200, {**_CLOCK, "contracts": {"mediation.schema.json": "c" * 64}})),
    ("fund", lambda c: c.fund("acct", 2500), "POST", "/test/funding", {},
     {"account": "acct", "amount": "2500"}, (200, {"account": "acct", "amount": "2500"})),
    ("rotate_signer", lambda c: c.rotate_signer(), "POST", "/test/signer/rotate", {}, None,
     (200, {"scheme": "ed25519", "identifier": "abc"})),
    ("cases", lambda c: c.cases(_TRANSACTION), "GET", "/test/cases",
     {"transaction": _TRANSACTION}, None, (200, {"cases": [_CASE]})),
    ("decide", lambda c: c.decide("case-1", _RULING), "POST", "/test/cases/case-1/decide", {},
     _RULING.model_dump(mode="json"), (200, {**_CASE, "state": "closed"})),
    ("close_case", lambda c: c.close_case("case-1"), "POST", "/test/cases/case-1/close", {},
     None, (200, {**_CASE, "state": "closed"})),
]


@pytest.mark.parametrize(("call", "method", "path", "query", "body", "answer"),
                         [entry[1:] for entry in _CALLS], ids=[entry[0] for entry in _CALLS])
def test_each_client_method_sends_its_routes_request_with_the_control_token(
        surface: _Surface, client: ControlClient, call: Callable[[ControlClient], Any],
        method: str, path: str, query: dict[str, str], body: Any,
        answer: tuple[int, Any]) -> None:
    surface.answer = answer

    result = call(client)

    request = surface.requests[-1]
    assert (request.method, request.url.path, dict(request.url.params)) == (method, path, query)
    assert surface.last_body() == body
    assert request.headers["authorization"] == f"Bearer {_TOKEN}"
    if answer[1] is not None:
        assert result.model_dump(mode="json", exclude_none=True) == answer[1]


def test_every_declared_route_has_a_client_method() -> None:
    called = {(method, re.sub(r"case-1|r\.1", "{}", path)) for _, _, method, path, *_ in _CALLS}
    declared = {(route.method, re.sub(r"\{[a-z_]+\}", "{}", route.path))
                for route in routes.ROUTES}

    assert called == declared


def test_a_rule_id_is_escaped_into_its_path(surface: _Surface, client: ControlClient) -> None:
    surface.answer = (404, {"code": "rule_not_found", "message": "no rule"})

    with pytest.raises(ControlError):
        client.delete_rule("a b")

    assert surface.requests[-1].url.raw_path == b"/test/rules/a%20b"


@pytest.mark.parametrize("code", get_args(ControlCode))
def test_each_refusal_code_is_raised_as_the_typed_error(
        surface: _Surface, client: ControlClient, code: str) -> None:
    surface.answer = (409, {"code": code, "message": f"refused as {code}"})

    with pytest.raises(ControlError) as refused:
        client.close_case("case-1")

    assert (refused.value.status, refused.value.code, refused.value.message) == (
        409, code, f"refused as {code}")


def test_an_answer_that_is_not_a_control_error_keeps_its_status(
        surface: _Surface, client: ControlClient) -> None:
    surface.answer = (404, {"detail": "Not Found"})

    with pytest.raises(ControlError) as refused:
        client.status()

    assert (refused.value.status, refused.value.code) == (404, "unexpected_response")


def test_the_client_trusts_the_configured_ca_bundle_alone(
        tls_generator: ModuleType, tmp_path: Path) -> None:
    for name, content in tls_generator.generate().items():
        (tmp_path / name).write_bytes(content)

    async def status_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        body = json.dumps({**_CLOCK, "contracts": {}}).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": body})

    with serving(status_app, certificate=tmp_path / "mediation-double.pem",
                 key=tmp_path / "mediation-double.key.pem") as origin:
        with ControlClient(origin, token=_TOKEN,
                           ca_bundle_path=str(tmp_path / "lane-ca.pem")) as trusted:
            assert trusted.status().offset_seconds == 60
        with ControlClient(origin, token=_TOKEN) as default_trust:
            with pytest.raises(httpx.ConnectError):
                default_trust.status()
