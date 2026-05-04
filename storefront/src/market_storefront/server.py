"""Storefront FastAPI application — entry point.

Mirrors provisioning-service/src/main.py:

* ``FastAPI(lifespan=lifespan)`` — resolves singletons, starts background tasks.
* ``app.include_router()`` for every controller router.
* ``AdminAuthMiddleware`` added after router registration.
* Auto-publish thread spawned in lifespan.

Global pause state
------------------
``_GLOBALLY_PAUSED`` is the module-level flag read by
``sync_negotiation.start_sync_negotiation``. Toggled by AdminController
via the module-level accessors exported below. Lives here to break the
circular import that would arise if sync_negotiation imported from agent.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import AdminAuthMiddleware
from market_storefront.utils.config import CONFIG
from market_storefront.utils.sqlite_client import get_sqlite_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global pause flag
# ---------------------------------------------------------------------------

_GLOBALLY_PAUSED: bool = False


def is_globally_paused() -> bool:
    return _GLOBALLY_PAUSED


def _set_globally_paused(value: bool) -> None:
    global _GLOBALLY_PAUSED
    _GLOBALLY_PAUSED = value


# ---------------------------------------------------------------------------
# Auto-publish helpers (previously in commands/serve.py)
# ---------------------------------------------------------------------------

def _wait_for_port(host: str, port: int, *, timeout: float = 30.0) -> bool:
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _spawn_publish_loop(*, host: str, port: int, poll_interval: float) -> threading.Thread | None:
    from market_storefront.cli_publish import run_watch_loop

    def _runner() -> None:
        if not _wait_for_port(host, port, timeout=30.0):
            logger.warning("[publish-loop] server not reachable within 30s; aborting")
            return
        try:
            run_watch_loop(
                db_path=CONFIG.agent_db_path,
                base_url=f"http://127.0.0.1:{port}",
                wallet_address=CONFIG.agent_wallet_address or "",
                private_key=CONFIG.agent_priv_key,
                default_min_price=CONFIG.default_min_price,
                default_token=CONFIG.default_token,
                default_max_duration_seconds=CONFIG.default_max_duration_seconds,
                poll_interval=poll_interval,
                log_silent_cycles=False,
            )
        except Exception as exc:
            logger.exception("[publish-loop] crashed: %r", exc)

    thread = threading.Thread(target=_runner, name="storefront-publish-loop", daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Public entry point (called by cli.py serve_cmd)
# ---------------------------------------------------------------------------

def run_serve(
    host: str = "0.0.0.0",
    port: int | None = None,
    *,
    no_publish: bool = False,
    poll_interval: float = 30.0,
) -> None:
    """Launch uvicorn with the FastAPI app. Called by ``market-storefront serve``."""
    import uvicorn

    resolved_port = port if port is not None else CONFIG.port
    if not no_publish:
        _spawn_publish_loop(host=host, port=resolved_port, poll_interval=poll_interval)
    else:
        logger.info("[serve] --no-publish flag set; skipping publish loop")
    uvicorn.run(app, host=host, port=resolved_port)


# ---------------------------------------------------------------------------
# Lifespan — init singletons, start background tasks
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI):
    from market_storefront.agent import _startup_tasks
    from market_storefront.services import alkahest_service
    from market_storefront.services.listing_service import ListingService
    from market_storefront.services.negotiation_service import NegotiationService
    from market_storefront.services.policy_pipeline_service import PolicyPipelineService
    from market_storefront.services.system_service import SystemService

    sqlite_client = get_sqlite_client()
    alkahest_client = alkahest_service.build_client(CONFIG)

    policy_pipeline = PolicyPipelineService(
        sqlite_client=sqlite_client,
        alkahest_client=alkahest_client,
        config=CONFIG,
        agent_id=CONFIG.agent_id,
    )
    listing_svc = ListingService(
        sqlite_client=sqlite_client,
        alkahest_client=alkahest_client,
        config=CONFIG,
    )
    negotiation_svc = NegotiationService(sqlite_client=sqlite_client)
    system_svc = SystemService(sqlite_client=sqlite_client, agent_id=CONFIG.agent_id)

    _container.resolved_sqlite_client = sqlite_client
    _container.resolved_alkahest_client = alkahest_client
    _container.resolved_policy_pipeline_service = policy_pipeline
    _container.resolved_listing_service = listing_svc
    _container.resolved_negotiation_service = negotiation_svc
    _container.resolved_system_service = system_svc

    logger.info("[STARTUP] Singletons initialized")
    await _startup_tasks()
    logger.info("[STARTUP] Background tasks started")

    yield

    logger.info("[SHUTDOWN] Storefront shutting down")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Arkhai Storefront",
    description="Seller-side storefront for the Arkhai compute marketplace.",
    version="1.0.0",
    lifespan=lifespan,
)

# Controller imports after module-level ``app`` and ``container`` exist,
# matching the provisioning-service main.py pattern.
from market_storefront.controllers.system_controller import router as system_router          # noqa: E402
from market_storefront.controllers.admin_controller import router as admin_router            # noqa: E402
from market_storefront.controllers.listings_controller import router as listings_router      # noqa: E402
from market_storefront.controllers.negotiations_controller import router as negotiations_router  # noqa: E402
from market_storefront.controllers.negotiate_controller import router as negotiate_router    # noqa: E402
from market_storefront.controllers.settle_controller import router as settle_router          # noqa: E402
from market_storefront.controllers.alerts_controller import router as alerts_router          # noqa: E402
from market_storefront.controllers.identity_controller import router as identity_router      # noqa: E402

app.include_router(system_router)
app.include_router(admin_router)
app.include_router(listings_router)
app.include_router(negotiations_router)
app.include_router(negotiate_router)
app.include_router(settle_router)
app.include_router(alerts_router)
app.include_router(identity_router)

app.add_middleware(AdminAuthMiddleware, admin_api_key=CONFIG.admin_api_key)
