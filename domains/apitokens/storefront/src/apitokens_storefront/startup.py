"""Storefront startup hooks: preflight + background tasks."""

from __future__ import annotations

import asyncio
import logging

from apitokens_storefront.utils import config
from apitokens_storefront.utils.config import BASE_URL_OVERRIDE, settings

logging.basicConfig(level=getattr(logging, str(settings.log_level).upper(), logging.INFO))

logger = logging.getLogger(__name__)


async def _preflight_tokens_service() -> None:
    """Block startup until the tokens service responds, or give up."""
    import httpx

    url = config.tokens_service_url()
    if not url:
        raise RuntimeError(
            "[STARTUP] [tokens].service_url is not configured — the "
            "storefront has nothing to sell for."
        )
    health = url + "/health"
    timeout_s = max(int(settings.get("tokens.preflight_timeout", 30)), 1)
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_error: str | None = None

    while True:
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                resp = await http.get(health)
            if resp.status_code == 200:
                logger.info("[STARTUP] Tokens service reachable at %s", url)
                return
            last_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(2.0, remaining))

    msg = (
        f"[STARTUP] Tokens service at {url} unreachable after {timeout_s}s "
        f"({last_error})."
    )
    if settings.get("tokens.fail_on_unreachable", True):
        raise RuntimeError(
            msg + " Set [tokens].fail_on_unreachable = false to start the "
            "storefront anyway (issuance will fail until it is reachable)."
        )
    logger.error(msg + " Continuing because fail_on_unreachable=false.")


async def _startup_tasks() -> None:
    """Initialize background tasks. Called from server.py lifespan."""
    import apitokens_storefront.container as _container
    from market_policy.identity import Identity
    from market_policy.negotiation_thread import get_thread_store

    storefront_url = BASE_URL_OVERRIDE or f"http://localhost:{settings.port}"
    get_thread_store(
        sqlite_client=_container.resolved_sqlite_client,
        identity=Identity(agent_url=storefront_url),
    )
    logger.info(
        "[STARTUP] Negotiation thread store initialized (storefront_url=%s)",
        storefront_url,
    )

    from apitokens_storefront.negotiation_watchdog import watchdog_loop

    asyncio.create_task(watchdog_loop())
    logger.info(
        "[STARTUP] Negotiation watchdog started (interval=%ds, timeout=%ds)",
        settings.negotiation_watchdog_interval,
        settings.negotiation_timeout_seconds,
    )

    from apitokens_storefront.services.claims_runtime import claims_engine_loop

    asyncio.create_task(claims_engine_loop())
    logger.info(
        "[STARTUP] Claims engine started (interval=%ss)",
        settings.get("claims_sweep_interval", 30),
    )

    await _preflight_tokens_service()

    from apitokens_storefront.services.capacity_client import (
        capacity_events_poller_loop,
    )

    asyncio.create_task(capacity_events_poller_loop())
    logger.info("[STARTUP] Quota capacity event poller started")
