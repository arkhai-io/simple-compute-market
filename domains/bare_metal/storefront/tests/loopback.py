"""Serve the in-process storefront app on a loopback port.

Some typed clients this storefront's routes answer to send through
``urllib`` and cannot take an injected ASGI transport: the production buyer's
fulfillment and introduction clients. To drive those routes through those
clients, the real app runs under uvicorn in a background thread on
``127.0.0.1`` with its lifespan, and the client is pointed at it.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn


@contextmanager
def serving(app: Any, *, startup_timeout: float = 10.0) -> Iterator[str]:
    """Run ``app`` until the block exits; yields its base URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + startup_timeout
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            server.should_exit = True
            raise RuntimeError("loopback storefront did not start")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=startup_timeout)
        sock.close()
