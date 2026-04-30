"""Run the storefront HTTP server in-process via uvicorn.

By default `serve` also runs the publish watch loop in a background
thread, so a single command brings up a live seller node. The thread
waits until the server's port is reachable, then loops the same logic
as ``market-storefront publish --watch``.

Auto-publish is opt-out (``--no-publish``), and only kicks in if the
operator has any pricing source configured: either per-row ``min_price``
on inventory, or a ``[seller.pricing].default_min_price`` fallback. With
no prices anywhere, there's nothing to publish anyway.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Optional


logger = logging.getLogger(__name__)


def _wait_for_port(host: str, port: int, *, timeout: float = 30.0) -> bool:
    """Poll until the TCP port is accepting connections, or timeout.

    The publish loop POSTs to /listings/create as soon as it can; before
    that succeeds we just retry quietly. Treat 0.0.0.0 as localhost for
    the connect side — uvicorn binds 0.0.0.0 but we connect via 127.0.0.1.
    """
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _spawn_publish_loop(
    *,
    host: str,
    port: int,
    poll_interval: float,
) -> Optional[threading.Thread]:
    """Spawn the publish watch loop in a daemon thread.

    Returns the thread (or None if there's no pricing configured and no
    inventory to publish). Caught exceptions log and exit the thread —
    server keeps running.
    """
    from market_storefront.cli_publish import run_watch_loop
    from market_storefront.utils.config import CONFIG

    db_path = CONFIG.agent_db_path
    default_min_price = CONFIG.default_min_price
    default_max_duration_seconds = CONFIG.default_max_duration_seconds
    base_url = f"http://127.0.0.1:{port}"
    wallet_address = CONFIG.agent_wallet_address or ""
    private_key = CONFIG.agent_priv_key

    def _runner() -> None:
        if not _wait_for_port(host, port, timeout=30.0):
            logger.warning(
                "[publish-loop] server didn't accept connections within 30s; aborting auto-publish"
            )
            return
        try:
            run_watch_loop(
                db_path=db_path, base_url=base_url,
                wallet_address=wallet_address,
                private_key=private_key,
                default_min_price=default_min_price,
                default_token=CONFIG.default_token,
                default_max_duration_seconds=default_max_duration_seconds,
                poll_interval=poll_interval,
                log_silent_cycles=False,
            )
        except Exception as exc:
            logger.exception("[publish-loop] crashed; auto-publish stopped: %r", exc)

    thread = threading.Thread(target=_runner, name="storefront-publish-loop", daemon=True)
    thread.start()
    return thread


def run_serve(
    host: str = "0.0.0.0",
    port: int | None = None,
    *,
    no_publish: bool = False,
    poll_interval: float = 30.0,
) -> None:
    import uvicorn

    from market_storefront.server import app
    from market_storefront.utils.config import CONFIG

    resolved_port = port if port is not None else CONFIG.port

    if not no_publish:
        _spawn_publish_loop(
            host=host,
            port=resolved_port,
            poll_interval=poll_interval,
        )
    else:
        logger.info("[serve] --no-publish: not starting the publish loop")

    uvicorn.run(app, host=host, port=resolved_port)
