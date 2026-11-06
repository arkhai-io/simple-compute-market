"""Serve the in-process storefront app on a loopback port.

The production buyer's negotiation client sends through ``urllib`` and cannot
take an injected ASGI transport. To drive the storefront's routes through that
client, the real app runs under uvicorn in a background thread on
``127.0.0.1`` with its lifespan, and the client is pointed at it.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn


class _LoopbackServer(uvicorn.Server):
    """A uvicorn server that stops on an event rather than at its next poll.

    Uvicorn's own main loop reads ``should_exit`` every tenth of a second, so
    each stop would wait for a poll. This loop waits on an event the stopping
    thread sets on the server's own event loop instead. Uvicorn's shutdown
    still pauses a tenth of a second for open connections to finish.
    """

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self.running = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    async def main_loop(self) -> None:
        self._stop = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self.running.set()
        await self.on_tick(0)
        if not self.should_exit:
            await self._stop.wait()

    def stop(self) -> None:
        # ``should_exit`` first: a main loop that has not yet made its event
        # reads it before waiting, and one that has is woken through its loop.
        self.should_exit = True
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)


@contextmanager
def serving(app: Any, *, startup_timeout: float = 10.0) -> Iterator[str]:
    """Run ``app`` until the block exits; yields its base URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = _LoopbackServer(uvicorn.Config(app, lifespan="on", log_level="warning"))

    def run() -> None:
        try:
            server.run(sockets=[sock])
        finally:
            # A server that failed to start ends here, and wakes the wait below.
            server.running.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not server.running.wait(startup_timeout) or not server.started:
        server.stop()
        raise RuntimeError("loopback storefront did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()
        thread.join(timeout=startup_timeout)
        sock.close()
