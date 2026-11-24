"""Serve an ASGI app on a loopback port.

An abandoned response is something a server does: uvicorn closes the connection
once an app returns from a response it started and did not finish. httpx's
in-process transport has no connection to close, so the fault tests run the app
under uvicorn in a background thread on ``127.0.0.1`` and point a real client at
it.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import uvicorn


class _LoopbackServer(uvicorn.Server):
    """A uvicorn server that stops on an event rather than at its next poll.

    Uvicorn's own main loop reads ``should_exit`` every tenth of a second, so
    each stop would wait for a poll. This loop waits on an event the stopping
    thread sets on the server's own event loop instead.
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
def serving(app: Any, *, certificate: Path | None = None, key: Path | None = None,
            startup_timeout: float = 10.0) -> Iterator[str]:
    """Run ``app`` until the block exits; yields its base URL.

    Given a certificate and its key, the app is served over HTTPS at
    ``localhost``, a name each lane double's leaf is issued for.
    """

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    # The faults' own abandonment is logged by uvicorn as an error; the tests
    # observe it at the client, so the log is not wanted here.
    server = _LoopbackServer(uvicorn.Config(
        app, lifespan="off", log_level="critical",
        ssl_certfile=None if certificate is None else str(certificate),
        ssl_keyfile=None if key is None else str(key)))
    origin = (f"http://127.0.0.1:{port}" if certificate is None
              else f"https://localhost:{port}")

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
        raise RuntimeError("loopback server did not start")
    try:
        yield origin
    finally:
        server.stop()
        thread.join(timeout=startup_timeout)
        sock.close()
