"""A sleep the test steps, so a loop's waits pass only when the test says."""

from __future__ import annotations

import asyncio

STEP_BOUND = 5


class SteppedSleep:
    """A sleep whose every wait ends only when the test steps it."""

    def __init__(self) -> None:
        self.asked: list[float] = []
        self._waits: asyncio.Queue[asyncio.Future[None]] = asyncio.Queue()
        self._pending: asyncio.Future[None] | None = None

    async def __call__(self, seconds: float) -> None:
        self.asked.append(seconds)
        waiting: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waits.put_nowait(waiting)
        await waiting

    async def waiting(self) -> None:
        """Return once the loop waits: everything before its wait has run."""

        if self._pending is None:
            self._pending = await asyncio.wait_for(self._waits.get(), STEP_BOUND)

    async def step(self) -> None:
        """End the loop's wait, and return once it waits again."""

        await self.waiting()
        assert self._pending is not None
        self._pending.set_result(None)
        self._pending = await asyncio.wait_for(self._waits.get(), STEP_BOUND)
