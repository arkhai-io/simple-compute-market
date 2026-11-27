"""The real gateway, gate, and gate client against an authority scripted at its HTTP boundary."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import uvicorn

from arkhai_api_gate import GateConfig, PurchasePointer, TokensClient
from arkhai_api_gateway import GatewayOffering, create_gateway_app

SERVICE = "served-model"
RESOURCE = "quota-1"
KEY_ID = "k_1"
SECRET = f"{KEY_ID}.buyer-secret"
DEFAULT_CHARGE = 5
PINNED_CHARGE = 2


class ScriptedAuthority:
    """Verifies one key and debits its balance, recording every request body it receives."""

    def __init__(self, *, balance: int, request_charge: int | None) -> None:
        self.balance = balance
        self.request_charge = request_charge
        self.verify_bodies: list[dict[str, Any]] = []
        self.consume_bodies: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == f"/api/v1/keys/{KEY_ID}/verify":
            self.verify_bodies.append(body)
            answer: dict[str, Any] = {
                "valid": body.get("secret") == SECRET, "status": "active", "balance": self.balance,
            }
            if self.request_charge is not None:
                answer.update(
                    accepted_terms={"rate_card": {}},
                    terms_digest="sha256:" + "b" * 64,
                    request_charge=self.request_charge,
                )
            return httpx.Response(200, json=answer)
        if request.url.path == f"/api/v1/keys/{KEY_ID}/consume":
            self.consume_bodies.append(body)
            if body["amount"] > self.balance:
                return httpx.Response(
                    402, json={"error": "insufficient_credits", "balance": self.balance},
                )
            self.balance -= body["amount"]
            return httpx.Response(
                200, json={"ok": True, "balance": self.balance, "consumed": body["amount"]},
            )
        raise AssertionError(f"unexpected authority request to {request.url.path}")


def _offering() -> GatewayOffering:
    return GatewayOffering(
        service=SERVICE,
        scope_service=SERVICE,
        scope_resource_id=RESOURCE,
        default_charge=DEFAULT_CHARGE,
        purchase=PurchasePointer(service_name=SERVICE, storefront_url="http://storefront"),
        upstream_base_url="http://model/v1",
    )


def _app(
    offering: GatewayOffering, authority: ScriptedAuthority, upstream: httpx.MockTransport,
) -> Any:
    client = TokensClient(
        service_url="http://authority",
        http=httpx.AsyncClient(transport=httpx.MockTransport(authority.handle)),
    )
    return create_gateway_app(
        offering,
        GateConfig(service_url="http://authority", authority_label="authority"),
        authority=client,
        http=httpx.AsyncClient(transport=upstream),
    )


def _completion_upstream(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"object": "chat.completion", "choices": [{"message": {"content": "hello"}}]},
        headers=[("x-upstream", "model"), ("set-cookie", "a=1"), ("set-cookie", "b=2")],
    )


async def _chat(app: Any, body: dict[str, Any]) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway",
    ) as client:
        return await client.post(
            "/v1/chat/completions", json=body, headers={"authorization": f"Bearer {SECRET}"},
        )


@pytest.mark.parametrize(
    ("request_charge", "charged"), [(PINNED_CHARGE, PINNED_CHARGE), (None, DEFAULT_CHARGE)],
)
async def test_an_admitted_request_is_relayed_and_charged_once(
    request_charge: int | None, charged: int,
) -> None:
    offering = _offering()
    authority = ScriptedAuthority(balance=10, request_charge=request_charge)
    app = _app(offering, authority, httpx.MockTransport(_completion_upstream))

    response = await _chat(app, {"model": SERVICE, "messages": []})

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello"
    assert response.headers["x-upstream"] == "model"
    assert response.headers.get_list("set-cookie") == ["a=1", "b=2"]
    assert [body["amount"] for body in authority.consume_bodies] == [charged]
    assert authority.balance == 10 - charged
    expected_scope = {"service": SERVICE, "resource_id": RESOURCE}
    assert authority.verify_bodies == [{"secret": SECRET, **expected_scope}]
    assert {k: authority.consume_bodies[0][k] for k in expected_scope} == expected_scope


async def test_an_unlisted_model_reaches_neither_the_authority_nor_the_model() -> None:
    offering = _offering()
    authority = ScriptedAuthority(balance=10, request_charge=None)
    forwarded: list[httpx.Request] = []
    app = _app(offering, authority, httpx.MockTransport(forwarded.append))

    response = await _chat(app, {"model": "other", "messages": []})

    assert response.status_code == 404
    assert authority.verify_bodies == authority.consume_bodies == []
    assert forwarded == []


async def test_an_exhausted_key_is_refused_with_the_purchase_pointer() -> None:
    offering = _offering()
    authority = ScriptedAuthority(balance=1, request_charge=PINNED_CHARGE)
    forwarded: list[httpx.Request] = []
    app = _app(offering, authority, httpx.MockTransport(forwarded.append))

    response = await _chat(app, {"model": SERVICE, "messages": []})

    assert response.status_code == 402
    assert response.json() == {
        "error": "insufficient_credits",
        "purchase": {"service_name": SERVICE, "storefront_url": "http://storefront"},
    }
    assert authority.balance == 1
    assert forwarded == []


class ControlledStream:
    """A model server that streams one event, then holds the last until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.sent_last = threading.Event()

    async def events(self) -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
        released = await asyncio.to_thread(self.release.wait, 10)
        assert released, "the test never released the last event"
        self.sent_last.set()
        yield b"data: [DONE]\n\n"

    def handle(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=self.events(),
        )


@pytest.fixture
def served_gateway() -> Iterator[tuple[str, ControlledStream, ScriptedAuthority]]:
    """The gateway served by uvicorn in a thread; ``ASGITransport`` cannot observe mid-stream events."""
    offering = _offering()
    authority = ScriptedAuthority(balance=10, request_charge=None)
    upstream = ControlledStream()
    app = _app(offering, authority, httpx.MockTransport(upstream.handle))
    # Listening before the server starts queues early connections instead of refusing them.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}", upstream, authority
    finally:
        upstream.release.set()
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def test_a_streamed_completion_reaches_the_buyer_before_the_model_finishes(
    served_gateway: tuple[str, ControlledStream, ScriptedAuthority],
) -> None:
    base_url, upstream, authority = served_gateway

    with httpx.Client(base_url=base_url, timeout=10) as client, client.stream(
        "POST",
        "/v1/chat/completions",
        json={"model": SERVICE, "stream": True, "messages": []},
        headers={"authorization": f"Bearer {SECRET}"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = response.iter_lines()
        first = next(lines)
        assert "first" in first
        assert not upstream.sent_last.is_set()
        upstream.release.set()
        rest = [line for line in lines if line]

    assert rest == ["data: [DONE]"]
    assert [body["amount"] for body in authority.consume_bodies] == [DEFAULT_CHARGE]
