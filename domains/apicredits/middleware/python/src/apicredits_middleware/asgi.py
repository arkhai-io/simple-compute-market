"""ASGI adapter — the Python framework binding of the token gate.

One file, per the design: all behavior lives in ``TokenGate``; this
just lifts the ``Authorization`` header out of the ASGI scope, asks the
gate, and either forwards to the app or writes the deny response. Works
under any ASGI server and mounts on FastAPI/Starlette via
``app.add_middleware(TokenGateMiddleware, gate=...)``.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Iterable

from .client import TokensClient
from .config import GateConfig
from .gate import GateDecision, TokenGate

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class TokenGateMiddleware:
    """Gate every HTTP request through a :class:`TokenGate`.

    Provide a ready ``gate``, or ``config`` (+ optional ``client``) to
    build one. ``exclude_paths`` are served without a token (health
    checks, the app's own docs). The gate's background flush loop is
    started on the ASGI ``lifespan.startup`` event and drained on
    ``lifespan.shutdown``.
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        gate: TokenGate | None = None,
        config: GateConfig | None = None,
        client: TokensClient | None = None,
        exclude_paths: Iterable[str] = ("/health",),
    ) -> None:
        if gate is None:
            if config is None:
                raise ValueError("TokenGateMiddleware needs either a gate or a config")
            client = client or TokensClient(
                service_url=config.service_url,
                admin_key=config.admin_key,
                timeout=config.request_timeout_seconds,
            )
            gate = TokenGate(config, client)
        self.app = app
        self.gate = gate
        self.exclude_paths = set(exclude_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path", "") in self.exclude_paths:
            await self.app(scope, receive, send)
            return

        authorization = _header(scope, b"authorization")
        decision = await self.gate.authorize(authorization)
        if decision.allowed:
            await self.app(scope, receive, send)
            return
        await _send_json(send, decision.status, decision.body or {})

    async def _lifespan(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def outer_receive() -> dict[str, Any]:
            message = await receive()
            if message["type"] == "lifespan.startup":
                self.gate.start()
            elif message["type"] == "lifespan.shutdown":
                await self.gate.aclose()
            return message

        await self.app(scope, outer_receive, send)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


async def _send_json(send: Send, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("latin-1")),
        ],
    })
    await send({"type": "http.response.body", "body": payload})


__all__ = ["TokenGateMiddleware", "GateDecision"]
