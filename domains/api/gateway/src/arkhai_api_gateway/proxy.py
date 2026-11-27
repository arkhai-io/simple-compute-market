"""Forwarding an admitted request to the model server."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse, Response, StreamingResponse

UPSTREAM_UNAVAILABLE = "upstream_unavailable"

# The buyer's Authorization must never reach the model server.
_FORWARDED_REQUEST_HEADERS = ("content-type", "accept")

# Hop-by-hop headers, plus encoding and length (the body is relayed decoded)
# and the date and server name the gateway's server writes itself.
_DROPPED_RESPONSE_HEADERS = frozenset({
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
    "date",
    "server",
})


async def forward(
    http: httpx.AsyncClient,
    url: str,
    body: bytes,
    request_headers: httpx.Headers,
    credential: str | None,
) -> Response:
    """POST ``body`` to ``url`` and relay the response as its bytes arrive, never read whole."""
    headers = {
        name: request_headers[name]
        for name in _FORWARDED_REQUEST_HEADERS
        if name in request_headers
    }
    if credential is not None:
        headers["authorization"] = f"Bearer {credential}"
    upstream_request = http.build_request("POST", url, content=body, headers=headers)
    try:
        upstream = await http.send(upstream_request, stream=True)
    except httpx.HTTPError:
        return JSONResponse({"error": UPSTREAM_UNAVAILABLE}, status_code=502)
    # The background close covers a caller that leaves before the first chunk,
    # when the relay's own finally never runs; closing twice is harmless.
    cleanup = BackgroundTasks()
    cleanup.add_task(upstream.aclose)
    response = StreamingResponse(
        _relay(upstream), status_code=upstream.status_code, background=cleanup,
    )
    # Raw pairs, so a repeated header such as set-cookie is relayed as sent.
    response.raw_headers.extend(
        (name, value)
        for name, value in upstream.headers.raw
        if name.decode("latin-1").lower() not in _DROPPED_RESPONSE_HEADERS
    )
    return response


async def _relay(upstream: httpx.Response) -> AsyncIterator[bytes]:
    # A background task does not run when the caller disconnects mid-stream,
    # so the relay closes the upstream itself.
    try:
        async for chunk in upstream.aiter_bytes():
            yield chunk
    finally:
        await upstream.aclose()
