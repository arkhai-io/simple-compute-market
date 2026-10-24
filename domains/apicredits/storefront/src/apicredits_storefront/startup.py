"""The storefront's startup preflight: the credits service must answer before trading starts."""

from __future__ import annotations

import asyncio
import logging

import httpx

from apicredits_storefront.utils import config
from apicredits_storefront.utils.config import settings

logging.basicConfig(
    level=getattr(logging, str(settings.get("log_level", "INFO")).upper(), logging.INFO)
)

logger = logging.getLogger(__name__)


async def preflight_credits_service() -> None:
    """Block startup until the credits service responds, or give up."""
    url = config.credits_service_url()
    if not url:
        raise RuntimeError(
            "[STARTUP] [credits].service_url is not configured — the "
            "storefront has nothing to sell for."
        )
    health = url + "/health"
    timeout_s = max(int(settings.get("credits.preflight_timeout", 30)), 1)
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_error: str | None = None

    while True:
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                resp = await http.get(health)
            if resp.status_code == 200:
                logger.info("[STARTUP] Credits service reachable at %s", url)
                return
            last_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(2.0, remaining))

    msg = (
        f"[STARTUP] Credits service at {url} unreachable after {timeout_s}s "
        f"({last_error})."
    )
    if settings.get("credits.fail_on_unreachable", True):
        raise RuntimeError(
            msg + " Set [credits].fail_on_unreachable = false to start the "
            "storefront anyway (issuance will fail until it is reachable)."
        )
    logger.error(msg + " Continuing because fail_on_unreachable=false.")
