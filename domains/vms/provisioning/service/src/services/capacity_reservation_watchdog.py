"""Capacity-reservation expiry watchdog.

CapacityReservationWatchdog is a thin asyncio timer that calls
CapacityLedgerService.expire_due_holds() on a configurable interval,
mirroring LeaseWatchdog exactly. All logic lives in CapacityLedgerService;
the watchdog only owns the scheduling. Every reserve/commit/release call
already lazily sweeps expired holds, so this exists only to reclaim a hold
left uncommitted at an otherwise-idle site (see
CapacityLedgerService.expire_due_holds's docstring).

Started as an asyncio background task in main.py lifespan:

    watchdog = CapacityReservationWatchdog(capacity_ledger_service, settings)
    asyncio.create_task(watchdog.run(), name="capacity-reservation-watchdog")
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class CapacityReservationWatchdog:
    """Periodic timer that delegates to CapacityLedgerService.expire_due_holds().

    All hold-expiry logic lives in CapacityLedgerService. This class only
    owns the asyncio scheduling and graceful shutdown.
    """

    def __init__(self, capacity_ledger_service, settings) -> None:
        self._svc = capacity_ledger_service
        self._settings = settings

    async def run(self) -> None:
        """Run the watchdog loop until cancelled."""
        interval = getattr(
            self._settings, "capacity_reservation_watchdog_poll_interval_seconds", 60
        )
        logger.info("[CAPACITY_RESERVATION_WATCHDOG] Started (interval=%ds)", interval)
        while True:
            try:
                await asyncio.sleep(interval)
                self._svc.expire_due_holds()
            except asyncio.CancelledError:
                logger.info("[CAPACITY_RESERVATION_WATCHDOG] Cancelled, shutting down")
                break
            except Exception as exc:
                logger.exception(
                    "[CAPACITY_RESERVATION_WATCHDOG] Unhandled error in cycle: %s", exc
                )
