"""The transport faults a lane double applies to its own API.

A caller of a double must meet the two transport failures a real service can
give it: a service that answers nothing, and a response lost after the request
committed. Each double wraps its ASGI app in ``TransportFaultMiddleware`` and
hands it a classifier, which decides from the request whether an installed rule
faults it and counts the match in that rule's listing.

A fault starts the response and then abandons it. The doubles run under uvicorn,
which answers ``500`` when an application raises before starting a response and
closes the connection only once one has started; so a fault starts a response
whose stated length is never sent, uvicorn closes the connection, and the caller's
httpx raises ``RemoteProtocolError``, which both kit clients count as a transport
error. A refusal status would not do: the mediation adapter reads a 5xx as pending
and a transport error as unknown, so a 5xx would prove the wrong branch.

Control routes and the health route are never faulted, and are never shown to the
classifier. A finaliser must always be able to remove the rule that caused a
fault, an orchestrator's liveness probe must not restart a double under an
outage, and no client under test calls either. For the same reason the
classifier runs on a worker thread, never on the event loop: a classifier may
read a collaborator to learn what a request matches, and the control and health
routes must keep answering while that read waits. A classifier is therefore
called from several threads at once and guards its own state.
"""

from __future__ import annotations

import asyncio
import enum
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from lane_double_controls.routes import is_contract_path

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]


class Fault(enum.Enum):
    #: Abandon the response without running the request.
    UNAVAILABLE = "unavailable"
    #: Run the request to completion, then abandon its response.
    DROP_AFTER_COMMIT = "drop_response_after_commit"


@dataclass(frozen=True)
class FaultRequest:
    """What a classifier sees of an API request: its method, path, headers and body."""

    method: str
    path: str
    #: Header names in lower case; a repeated header keeps its last value.
    headers: Mapping[str, str]
    body: bytes


Classifier = Callable[[FaultRequest], Fault | None]


class TransportFaultMiddleware:
    """Applies the fault ``classify`` names to each request outside the control and health routes."""

    def __init__(self, app: App, classify: Classifier) -> None:
        self.app = app
        self.classify = classify

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_contract_path(scope["path"]):
            await self.app(scope, receive, send)
            return
        body = await _read_body(receive)
        headers = {name.decode("latin-1").lower(): value.decode("latin-1")
                   for name, value in scope.get("headers", [])}
        fault = await asyncio.to_thread(
            self.classify,
            FaultRequest(method=scope["method"], path=scope["path"], headers=headers, body=body))
        replay = _replay(body, receive)
        if fault is None:
            await self.app(scope, replay, send)
        elif fault is Fault.UNAVAILABLE:
            await _abandon(send, 200)
        else:
            status = 200

            async def discard(message: Message) -> None:
                nonlocal status
                if message["type"] == "http.response.start":
                    status = message["status"]

            await self.app(scope, replay, discard)
            await _abandon(send, status)


async def _read_body(receive: Receive) -> bytes:
    chunks = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    """A ``receive`` that hands the app the body already read, then defers to the server."""

    delivered = False

    async def replay() -> Message:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replay


async def _abandon(send: Send, status: int) -> None:
    # The stated length is never sent, so whatever framing the server chooses, the
    # caller cannot mistake the closed connection for a complete, empty answer.
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-length", b"1")]})


__all__ = ["Classifier", "Fault", "FaultRequest", "TransportFaultMiddleware"]
