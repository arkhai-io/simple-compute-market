"""Serve the in-process storefront app on a loopback port.

Some typed clients this storefront's routes answer to send through
``urllib`` and cannot take an injected ASGI transport: the production buyer's
fulfillment and introduction clients. To drive those routes through those
clients, the real app runs under uvicorn in a background thread on
``127.0.0.1`` with its lifespan, and the client is pointed at it. Where the
app's routes start tasks a test's composition must await at teardown, the app
runs on the test's own event loop instead (:func:`served`).
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
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


def _loopback_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    return sock


@contextmanager
def serving(app: Any, *, startup_timeout: float = 10.0) -> Iterator[str]:
    """Run ``app`` until the block exits; yields its base URL."""
    sock = _loopback_socket()
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


@asynccontextmanager
async def served(app: Any, *, startup_timeout: float = 10.0) -> AsyncIterator[str]:
    """Run ``app`` on the calling event loop until the block exits; yields its base URL.

    Tasks the app's routes start then belong to the test's own loop, so a
    composition the test tears down after the server stops can still await
    them; under :func:`serving` they would belong to a loop already closed. A
    client driving the app must then run off this loop, in a worker thread.
    """
    sock = _loopback_socket()
    port = sock.getsockname()[1]
    server = _LoopbackServer(uvicorn.Config(app, lifespan="on", log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    # A server that failed to start ends its task, and wakes the wait below.
    task.add_done_callback(lambda _: server.running.set())
    try:
        started = await asyncio.to_thread(server.running.wait, startup_timeout)
        if not started or not server.started:
            raise RuntimeError("loopback storefront did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()
        await asyncio.wait_for(task, startup_timeout)
        sock.close()
