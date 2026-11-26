from __future__ import annotations

import asyncio
from typing import Any

import pytest

from request_replay.asgi import capture, read_body, replayed_receive, send_response


def channel(*messages: dict[str, Any]):
    queue = list(messages)

    async def receive() -> dict[str, Any]:
        return queue.pop(0)

    return receive


async def echo(scope: Any, receive: Any, send: Any) -> None:
    body = await read_body(receive)
    await send({"type": "http.response.start", "status": 202, "headers": [(b"x-seen", b"1")]})
    await send({"type": "http.response.body", "body": body[:3], "more_body": True})
    await send({"type": "http.response.body", "body": body[3:]})


def test_a_body_sent_in_chunks_is_read_whole() -> None:
    receive = channel(
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def"},
    )

    assert asyncio.run(read_body(receive)) == b"abcdef"


def test_a_disconnect_before_the_body_ends_is_refused() -> None:
    receive = channel({"type": "http.request", "body": b"abc", "more_body": True}, {"type": "http.disconnect"})

    with pytest.raises(ConnectionError):
        asyncio.run(read_body(receive))


def test_an_application_runs_on_the_buffered_body_and_its_response_is_held_whole() -> None:
    later = channel({"type": "http.disconnect"})

    async def run() -> tuple[Any, dict[str, Any]]:
        receive = replayed_receive(b"payload", later)
        captured = await capture(echo, {"type": "http"}, receive)
        return captured, await receive()

    captured, after = asyncio.run(run())

    assert (captured.status, captured.headers, captured.body) == (202, [(b"x-seen", b"1")], b"payload")
    assert after == {"type": "http.disconnect"}


def test_an_application_error_propagates_from_capture() -> None:
    async def failing(scope: Any, receive: Any, send: Any) -> None:
        raise LookupError("broken")

    with pytest.raises(LookupError):
        asyncio.run(capture(failing, {"type": "http"}, channel()))


def test_a_whole_response_is_sent_as_two_messages() -> None:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(send_response(send, 410, [(b"content-type", b"application/json")], b"{}"))

    assert sent == [
        {"type": "http.response.start", "status": 410, "headers": [(b"content-type", b"application/json")]},
        {"type": "http.response.body", "body": b"{}", "more_body": False},
    ]
