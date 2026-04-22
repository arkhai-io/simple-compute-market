"""Unit tests for the outbound HTTP dispatcher (service/clients/agent_http.py).

Mocks aiohttp and exercises the success + failure paths. The tests don't
go through a real event loop for HTTP; they just verify that
`send_message` produces the right URL, JSON body, and error-surfacing
behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from service.clients.agent_http import AgentDispatchError, send_message


class _FakeResponse:
    def __init__(self, *, status: int, text: str = ""):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def text(self):
        return self._text


class _FakeSession:
    def __init__(self, response: _FakeResponse, *, raise_on_post: Exception | None = None):
        self.response = response
        self.raise_on_post = raise_on_post
        self.last_url: str | None = None
        self.last_json: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def post(self, url, *, json):
        self.last_url = url
        self.last_json = json
        if self.raise_on_post:
            raise self.raise_on_post
        return self.response


@pytest.mark.asyncio
async def test_send_message_happy_path():
    fake = _FakeSession(_FakeResponse(status=200, text='{"status":"received","event_id":"e1"}'))

    with patch("service.clients.agent_http.aiohttp.ClientSession", return_value=fake):
        result = await send_message(
            peer_url="http://alice:8000",
            path="/negotiation/offer",
            envelope={"schema_id": "x", "payload": {}},
        )

    assert result == {"status": "received", "event_id": "e1"}
    assert fake.last_url == "http://alice:8000/negotiation/offer"
    assert fake.last_json == {"schema_id": "x", "payload": {}}


@pytest.mark.asyncio
async def test_send_message_normalizes_missing_leading_slash():
    fake = _FakeSession(_FakeResponse(status=200, text="{}"))
    with patch("service.clients.agent_http.aiohttp.ClientSession", return_value=fake):
        await send_message(
            peer_url="http://alice:8000/",
            path="negotiation/offer",
            envelope={},
        )
    assert fake.last_url == "http://alice:8000/negotiation/offer"


@pytest.mark.asyncio
async def test_send_message_empty_response_body_returns_empty_dict():
    fake = _FakeSession(_FakeResponse(status=200, text=""))
    with patch("service.clients.agent_http.aiohttp.ClientSession", return_value=fake):
        result = await send_message(
            peer_url="http://alice:8000",
            path="/negotiation/exit",
            envelope={},
        )
    assert result == {}


@pytest.mark.asyncio
async def test_send_message_surfaces_4xx_body():
    fake = _FakeSession(_FakeResponse(status=415, text='{"error":"unsupported schema"}'))
    with patch("service.clients.agent_http.aiohttp.ClientSession", return_value=fake):
        with pytest.raises(AgentDispatchError, match="HTTP 415"):
            await send_message(
                peer_url="http://alice:8000",
                path="/negotiation/offer",
                envelope={},
            )


@pytest.mark.asyncio
async def test_send_message_rejects_non_json_body():
    fake = _FakeSession(_FakeResponse(status=200, text="<html>nope</html>"))
    with patch("service.clients.agent_http.aiohttp.ClientSession", return_value=fake):
        with pytest.raises(AgentDispatchError, match="non-JSON body"):
            await send_message(
                peer_url="http://alice:8000",
                path="/negotiation/offer",
                envelope={},
            )


@pytest.mark.asyncio
async def test_send_message_refuses_empty_peer_url():
    with pytest.raises(AgentDispatchError, match="peer_url is required"):
        await send_message(peer_url="", path="/foo", envelope={})


@pytest.mark.asyncio
async def test_send_message_surfaces_aiohttp_client_error():
    import aiohttp

    fake = _FakeSession(
        _FakeResponse(status=200, text="{}"),
        raise_on_post=aiohttp.ClientConnectorError(
            MagicMock(ssl=None), OSError("connection refused"),
        ),
    )
    with patch("service.clients.agent_http.aiohttp.ClientSession", return_value=fake):
        with pytest.raises(AgentDispatchError, match="failed"):
            await send_message(
                peer_url="http://alice:8000",
                path="/negotiation/offer",
                envelope={},
            )
