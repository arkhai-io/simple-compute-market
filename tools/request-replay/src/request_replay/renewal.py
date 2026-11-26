"""Holding an attempt's lease for as long as its handler runs.

A recorded request is never dispatched twice, so a retry that finds its lease
ended is told the outcome is unknown, and its caller reads current state before
writing again. That answer is true only if the attempt has ended: a handler still
running past a fixed lease could commit after the caller's read. So while a
handler runs, its lease is renewed every third of the period, and an attempt
loses it only when its process is gone or cannot renew it for a whole period: a
handler that blocks the event loop that long, or a store that refuses every
renewal that long -- under SQLite, a handler of its own holding the write lock.
Such a loss is logged as an error naming the request, since a retry is then told
the outcome is unknown while the attempt can still commit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from request_replay.guard import Attempt, RequestReplay

logger = logging.getLogger(__name__)


class Renewal:
    """A running attempt's lease renewal, started and stopped by its holder.

    Renews every third of the lease period from :meth:`start` until :meth:`stop`,
    or until the lease is lost; a loss is logged once, whether a renewal finds it
    or the holder stops after the lease ended. An attempt shorter than a third
    of its lease writes nothing. ``sleep`` waits a duration of this process's own
    activity, so it runs on the monotonic clock, never the time source the lease
    is written on, which a test may hold or move. A holder whose start and stop
    sit in one block uses :func:`renewing`; one that starts renewal where a
    request is admitted and stops it where the response is complete holds this.
    """

    def __init__(
        self,
        replay: RequestReplay,
        attempt: Attempt,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._replay = replay
        self._attempt = attempt
        self._lease_until = attempt.lease_until
        self._lost = False
        self._task = asyncio.create_task(self._renew_until_lost(sleep))

    @classmethod
    def start(
        cls,
        replay: RequestReplay,
        attempt: Attempt,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> Renewal:
        return cls(replay, attempt, sleep)

    def cancel(self) -> None:
        """Stop renewing without waiting, as a holder being cancelled itself must."""

        self._task.cancel()
        # The lease may have ended between renewals, with the handler done
        # before the next found it.
        if self._ended():
            self._report_lost()

    async def stop(self) -> None:
        self.cancel()
        # Waiting raises nothing of the renewal task's, but still raises a
        # cancellation of the task stopping it.
        await asyncio.wait({self._task})

    def _ended(self) -> bool:
        return self._replay.now() >= self._lease_until

    async def _renew_until_lost(self, sleep: Callable[[float], Awaitable[None]]) -> None:
        attempt = self._attempt
        interval = self._replay.policy.lease_seconds / 3
        while True:
            await sleep(interval)
            try:
                renewed = self._replay.renew(attempt)
            except Exception:
                if self._ended():
                    self._report_lost(exc_info=True)
                    return
                # A store that failed once, a lock held too long say, is tried
                # again at the next interval, before the lease ends: giving up
                # would let it end while the handler can still commit.
                logger.exception(
                    "renewing the lease of request %s of %s failed; retrying",
                    attempt.request_id,
                    attempt.principal,
                )
                continue
            if renewed is None:
                self._report_lost()
                return
            self._lease_until = renewed

    def _report_lost(self, *, exc_info: bool = False) -> None:
        if self._lost:
            return
        self._lost = True
        logger.error(
            "request %s of %s lost its lease while its handler runs: an exact retry is "
            "answered that its outcome is unknown, though this attempt can still commit",
            self._attempt.request_id,
            self._attempt.principal,
            exc_info=exc_info,
        )


@contextlib.asynccontextmanager
async def renewing(
    replay: RequestReplay,
    attempt: Attempt,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[None]:
    """Renew ``attempt``'s lease while the body runs, as :class:`Renewal` does.

    Renewal stops when the body returns or raises.
    """

    renewal = Renewal.start(replay, attempt, sleep=sleep)
    try:
        yield
    finally:
        await renewal.stop()
