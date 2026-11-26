"""Running an ASGI application on a buffered request and capturing its response.

A guard admits a request only once it has read the whole body, which its hash
covers, and records a response only once it has the whole of it. A middleware
uses these to hand the application the body it already read, and to hold the
response until it is recorded and answered. They depend on no web framework.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

Message = MutableMapping[str, Any]
Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


async def read_body(receive: Receive) -> bytes:
    """Every byte of an HTTP request's body."""

    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise ConnectionError("the client disconnected before its request body was read")
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


def replayed_receive(body: bytes, receive: Receive) -> Receive:
    """A receive that yields ``body`` once, then what ``receive`` yields.

    After the body, the application waits on the real channel, so it still
    learns of a disconnect.
    """

    sent = False

    async def replay() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


@dataclass
class CapturedResponse:
    """A response an application sent, held whole."""

    status: int = 500
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    body: bytes = b""


async def capture(app: ASGIApp, scope: Scope, receive: Receive) -> CapturedResponse:
    """Run ``app`` and return the response it sent, sending nothing on.

    An error the application raises propagates, whatever it had sent before.
    """

    captured = CapturedResponse()
    chunks: list[bytes] = []

    async def hold(message: Message) -> None:
        if message["type"] == "http.response.start":
            captured.status = int(message["status"])
            captured.headers = [(bytes(name), bytes(value)) for name, value in message.get("headers", [])]
        elif message["type"] == "http.response.body":
            chunks.append(bytes(message.get("body", b"")))

    await app(scope, receive, hold)
    captured.body = b"".join(chunks)
    return captured


async def send_response(send: Send, status: int, headers: list[tuple[bytes, bytes]], body: bytes) -> None:
    """Send a whole response."""

    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})
