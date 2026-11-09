"""The transport-fault middleware, behind a real server, as a caller meets it.

A minimal ASGI app counts the requests it commits and echoes their bodies; the
middleware wraps it with a classifier the test sets, and uvicorn serves it on
loopback, so each fault is observed where a double's caller observes it: in
httpx, as a transport error and never as an HTTP status.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from loopback import serving

from lane_double_controls.middleware import Fault, FaultRequest, TransportFaultMiddleware


class _Ledger:
    """The app's committed requests, and what the classifier saw and answered."""

    def __init__(self) -> None:
        self.committed: list[bytes] = []
        self.fault: Fault | None = None
        self.classified: list[FaultRequest] = []

    def classify(self, request: FaultRequest) -> Fault | None:
        self.classified.append(request)
        return self.fault

    async def app(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        assert scope["type"] == "http"
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        if not scope["path"].startswith("/test/"):
            self.committed.append(body)
        payload = json.dumps({"path": scope["path"], "body": body.decode(),
                              "committed": len(self.committed)}).encode()
        await send({"type": "http.response.start", "status": 201,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(payload)).encode())]})
        await send({"type": "http.response.body", "body": payload})


@pytest.fixture
def ledger() -> _Ledger:
    return _Ledger()


@pytest.fixture
def client(ledger: _Ledger) -> Iterator[httpx.Client]:
    with serving(TransportFaultMiddleware(ledger.app, ledger.classify)) as base_url:
        with httpx.Client(base_url=base_url, trust_env=False, timeout=10.0) as http:
            yield http


def test_without_a_fault_the_request_and_its_body_reach_the_app(
        ledger: _Ledger, client: httpx.Client) -> None:
    response = client.post("/transactions/abc/events", content=b'{"kind":"stop"}',
                           headers={"Authorization": "Bearer t", "Idempotency-Key": "k1"})

    assert response.status_code == 201
    assert response.json()["body"] == '{"kind":"stop"}'
    seen = ledger.classified[-1]
    assert (seen.method, seen.path, seen.body) == (
        "POST", "/transactions/abc/events", b'{"kind":"stop"}')
    assert seen.headers["authorization"] == "Bearer t"
    assert seen.headers["idempotency-key"] == "k1"


def test_unavailable_abandons_an_api_response_without_running_it(
        ledger: _Ledger, client: httpx.Client) -> None:
    ledger.fault = Fault.UNAVAILABLE

    with pytest.raises(httpx.RemoteProtocolError):
        client.post("/transactions", content=b"{}")
    assert ledger.committed == []


def test_unavailable_never_reaches_a_control_route(
        ledger: _Ledger, client: httpx.Client) -> None:
    ledger.fault = Fault.UNAVAILABLE

    response = client.get("/test/status")

    assert response.status_code == 201
    assert ledger.classified == []


def test_unavailable_never_reaches_the_health_route(
        ledger: _Ledger, client: httpx.Client) -> None:
    ledger.fault = Fault.UNAVAILABLE

    assert client.get("/health").status_code == 201
    assert ledger.classified == []


def test_removing_the_fault_restores_the_api(ledger: _Ledger, client: httpx.Client) -> None:
    ledger.fault = Fault.UNAVAILABLE
    with pytest.raises(httpx.RemoteProtocolError):
        client.get("/balances/x")

    ledger.fault = None

    assert client.get("/balances/x").status_code == 201


def test_drop_after_commit_runs_the_request_once_and_loses_its_response(
        ledger: _Ledger, client: httpx.Client) -> None:
    ledger.fault = Fault.DROP_AFTER_COMMIT

    with pytest.raises(httpx.RemoteProtocolError):
        client.post("/transactions", content=b'{"mandate":1}')
    assert ledger.committed == [b'{"mandate":1}']

    ledger.fault = None
    retried = client.post("/transactions", content=b'{"mandate":1}')

    assert retried.json()["committed"] == 2


def test_control_and_health_routes_answer_while_a_classification_waits(
        ledger: _Ledger) -> None:
    # A classifier may wait on a collaborator; the server must keep answering
    # the routes the classifier never sees meanwhile.
    entered, release = threading.Event(), threading.Event()

    def classify(request: FaultRequest) -> Fault | None:
        entered.set()
        release.wait(timeout=10.0)
        return None

    with serving(TransportFaultMiddleware(ledger.app, classify)) as base_url:
        with httpx.Client(base_url=base_url, trust_env=False, timeout=10.0) as waiting, \
                httpx.Client(base_url=base_url, trust_env=False, timeout=2.0) as prompt:
            answers: list[int] = []
            caller = threading.Thread(
                target=lambda: answers.append(waiting.post("/cases", content=b"{}").status_code))
            caller.start()
            try:
                assert entered.wait(timeout=10.0)
                assert prompt.get("/test/status").status_code == 201
                assert prompt.get("/health").status_code == 201
                assert answers == []
            finally:
                release.set()
                caller.join(timeout=10.0)

    assert answers == [201]


def test_a_fault_is_a_transport_error_to_the_kit_clients_definition(
        ledger: _Ledger, client: httpx.Client) -> None:
    # Both kit clients turn httpx's transport errors into their own transport
    # error; a fault must land there, never as a response with a status.
    ledger.fault = Fault.DROP_AFTER_COMMIT

    with pytest.raises(httpx.TransportError):
        client.get("/transactions/abc")
