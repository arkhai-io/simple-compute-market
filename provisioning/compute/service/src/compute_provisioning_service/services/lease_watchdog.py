"""Lease expiry watchdog.

LeaseWatchdog is a thin asyncio timer that calls LeaseLifecycleService.check_leases()
on a configurable interval. All logic lives in LeaseLifecycleService; the watchdog
only owns the scheduling.

Started as an asyncio background task in main.py lifespan:

    watchdog = LeaseWatchdog(lease_lifecycle_service, settings)
    asyncio.create_task(watchdog.run(), name="lease-watchdog")

Operators and tests trigger an immediate cycle via:

    POST /api/v1/system/check-leases
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class LeaseWatchdog:
    """Periodic timer that delegates to LeaseLifecycleService.check_leases().

    All lease logic lives in LeaseLifecycleService. This class only owns the
    asyncio scheduling and graceful shutdown.
    """

    def __init__(self, lease_lifecycle_service, settings) -> None:
        self._svc = lease_lifecycle_service
        self._settings = settings

    async def run(self) -> None:
        """Run the watchdog loop until cancelled."""
        interval = getattr(self._settings, "lease_watchdog_poll_interval_seconds", 60)
        logger.info("[LEASE_WATCHDOG] Started (interval=%ds)", interval)
        while True:
            try:
                await asyncio.sleep(interval)
                await self._svc.check_leases()
            except asyncio.CancelledError:
                logger.info("[LEASE_WATCHDOG] Cancelled, shutting down")
                break
            except Exception as exc:
                logger.exception("[LEASE_WATCHDOG] Unhandled error in cycle: %s", exc)
