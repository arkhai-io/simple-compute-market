"""A recorded request's lease is renewed while its handler runs.

The renewal's waits are stepped by the test, never slept: each step ends one
wait, and returns once the renewal has written and waits again.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable

from request_replay import Answered, Dispatch, InProgress, Resolution, renewing

from tests.support import OUTCOME, POLICY, START, ManualClock, entry, guard

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

    async def step(self) -> None:
        if self._pending is None:
            self._pending = await asyncio.wait_for(self._waits.get(), STEP_BOUND)
        self._pending.set_result(None)
        self._pending = await asyncio.wait_for(self._waits.get(), STEP_BOUND)


def test_a_handler_running_past_its_lease_is_renewed_then_its_outcome_answers(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    request = entry(Resolution.RECORDED)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(request)
        assert isinstance(first, Dispatch)
        finish = asyncio.Event()

        async def handler() -> None:
            async with renewing(replay, first.attempt, sleep=sleep):
                await finish.wait()
            replay.complete(first.attempt, OUTCOME)

        running = asyncio.create_task(handler())
        clock.advance(10)
        await sleep.step()
        clock.advance(25)
        assert clock() > START + POLICY.lease_seconds
        assert replay.admit(request) == InProgress()

        await sleep.step()
        clock.advance(25)
        assert replay.admit(request) == InProgress()

        finish.set()
        await asyncio.wait_for(running, STEP_BOUND)
        assert sleep.asked and set(sleep.asked) == {POLICY.lease_seconds / 3}

    asyncio.run(scenario())

    assert replay.admit(request) == Answered(OUTCOME)


def test_an_attempt_shorter_than_a_third_of_its_lease_writes_no_renewal(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(entry(Resolution.RECORDED))
        assert isinstance(first, Dispatch)
        async with renewing(replay, first.attempt, sleep=sleep):
            await asyncio.sleep(0)
        assert sleep.asked == [POLICY.lease_seconds / 3]

    asyncio.run(scenario())

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert row.lease_until == START + POLICY.lease_seconds


def test_renewal_stops_when_the_handler_raises(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(entry(Resolution.RECORDED))
        assert isinstance(first, Dispatch)
        try:
            async with renewing(replay, first.attempt, sleep=sleep):
                raise LookupError("handler failed")
        except LookupError:
            pass
        await asyncio.sleep(0)
        assert all(task is asyncio.current_task() for task in asyncio.all_tasks())

    asyncio.run(scenario())


def _recorded_attempt(store: object, clock: ManualClock) -> tuple[Callable[[], object], object]:
    replay = guard(store, clock)
    first = replay.admit(entry(Resolution.RECORDED))
    assert isinstance(first, Dispatch)
    return replay, first.attempt


def test_a_renewal_after_the_record_leaves_the_outcome_and_no_lease(store) -> None:
    clock = ManualClock()
    replay, attempt = _recorded_attempt(store, clock)

    replay.complete(attempt, OUTCOME)
    assert replay.renew(attempt) is False

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert (row.outcome, row.lease_until, row.lease_owner) == (OUTCOME, None, None)


def test_a_renewal_before_the_record_leaves_the_outcome_and_no_lease(store) -> None:
    clock = ManualClock()
    replay, attempt = _recorded_attempt(store, clock)

    clock.advance(10)
    assert replay.renew(attempt) is True
    replay.complete(attempt, OUTCOME)

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert (row.outcome, row.lease_until, row.lease_owner) == (OUTCOME, None, None)


class FailingOnce:
    """A store whose first renewal fails, as under a write lock held too long."""

    def __init__(self, store: object) -> None:
        self._store = store
        self.failed = False

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def renew(self, *args: object, **kwargs: object) -> bool:
        if not self.failed:
            self.failed = True
            raise sqlite3.OperationalError("database is locked")
        return bool(self._store.renew(*args, **kwargs))  # type: ignore[attr-defined]


def test_a_renewal_that_fails_once_is_tried_again_before_the_lease_ends(store) -> None:
    clock = ManualClock()
    failing = FailingOnce(store)
    replay = guard(failing, clock)
    request = entry(Resolution.RECORDED)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(request)
        assert isinstance(first, Dispatch)
        finish = asyncio.Event()

        async def handler() -> None:
            async with renewing(replay, first.attempt, sleep=sleep):
                await finish.wait()

        running = asyncio.create_task(handler())
        clock.advance(10)
        await sleep.step()
        assert failing.failed
        clock.advance(10)
        await sleep.step()
        clock.advance(25)
        assert replay.admit(request) == InProgress()
        finish.set()
        await asyncio.wait_for(running, STEP_BOUND)

    asyncio.run(scenario())
