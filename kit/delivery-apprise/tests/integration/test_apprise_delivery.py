"""The Apprise sink delivering to a real local receiver through Apprise itself."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from market_delivery import DeliveryError, introduction_delivery_event
from market_delivery_apprise import build_apprise_sink


def _event():
    return introduction_delivery_event(
        {
            "obligation_ref": "a" * 64,
            "revealed": True,
            "introduction": {"channel": "email"},
            "counterparty_contact": {"email": "buyer@example.com"},
        },
        role="seller",
    )


class _Receiver:
    def __init__(self, status: int = 200) -> None:
        received: list[dict] = []
        reply = status

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server naming
                length = int(self.headers.get("Content-Length", 0))
                received.append(json.loads(self.rfile.read(length) or b"{}"))
                self.send_response(reply)
                self.end_headers()

            def log_message(self, *args) -> None:
                return

        self.received = received
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"json://127.0.0.1:{self.server.server_address[1]}/introductions"

    def __enter__(self) -> _Receiver:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()


def test_an_event_reaches_the_service_its_url_names() -> None:
    with _Receiver() as receiver:
        sink = build_apprise_sink({"urls": [receiver.url], "title": "New introduction"})
        sink(_event())
    (message,) = receiver.received
    assert message["title"] == "New introduction"
    assert "buyer@example.com" in message["message"]


def test_a_refusing_service_is_reported_without_the_url() -> None:
    with _Receiver(status=500) as receiver:
        sink = build_apprise_sink({"urls": [receiver.url]})
        with pytest.raises(DeliveryError) as caught:
            sink(_event())
    assert "127.0.0.1" not in str(caught.value)
    assert "buyer@example.com" not in str(caught.value)
