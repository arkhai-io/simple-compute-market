"""Holding an attempt's lease for as long as its handler runs.

A recorded request is never dispatched twice, so a retry that finds its lease
ended is told the outcome is unknown, and its caller reads current state before
writing again. That answer is true only if the attempt has ended: a handler still
running past a fixed lease could commit after the caller's read. So while a
handler runs, its lease is renewed every third of the period, and only an attempt
whose process is gone loses it. A handler that blocks the event loop for a whole
period stalls its renewal.
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

    Renews every third of the lease period from :meth:`start` until :meth:`stop`.
    An attempt shorter than a third of its lease writes nothing. ``sleep`` waits
    a duration of this process's own activity, so it runs on the monotonic
    clock, never the time source the lease is written on, which a test may hold
    or move. A holder whose start and stop sit in one block uses
    :func:`renewing`; one that starts renewal where a request is admitted and
    stops it where the response is complete holds this.
    """

    def __init__(self, task: asyncio.Task[None]) -> None:
        self._task = task

    @classmethod
    def start(
        cls,
        replay: RequestReplay,
        attempt: Attempt,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> Renewal:
        return cls(asyncio.create_task(_renew_until_lost(replay, attempt, sleep)))

    def cancel(self) -> None:
        """Stop renewing without waiting, as a holder being cancelled itself must."""

        self._task.cancel()

    async def stop(self) -> None:
        self.cancel()
        # Waiting raises nothing of the renewal task's, but still raises a
        # cancellation of the task stopping it.
        await asyncio.wait({self._task})


async def _renew_until_lost(
    replay: RequestReplay, attempt: Attempt, sleep: Callable[[float], Awaitable[None]]
) -> None:
    interval = replay.policy.lease_seconds / 3
    while True:
        await sleep(interval)
        try:
            renewed = replay.renew(attempt)
        except Exception:
            # A store that failed once, a lock held too long say, is tried
            # again at the next interval, before the lease ends: giving up
            # would let it end while the handler can still commit.
            logger.exception(
                "renewing the lease of request %s of %s failed; retrying",
                attempt.request_id,
                attempt.principal,
            )
            continue
        if not renewed:
            logger.warning(
                "request %s of %s lost its lease while its handler ran",
                attempt.request_id,
                attempt.principal,
            )
            return


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
