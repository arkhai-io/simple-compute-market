"""A recorded request's lease is renewed while its handler runs.

The renewal's waits are stepped by the test, never slept: each step ends one
wait, and returns once the renewal has written and waits again.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable

import pytest
from request_replay import Answered, Dispatch, InProgress, OutcomeUnknown, Renewal, Resolution, renewing

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

    async def last_step(self) -> None:
        """End the loop's wait when the test expects it not to wait again."""

        if self._pending is None:
            self._pending = await asyncio.wait_for(self._waits.get(), STEP_BOUND)
        self._pending.set_result(None)
        self._pending = None


LOST = "lost its lease while its handler runs"


def losses(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if LOST in record.getMessage()]


def logged_one_loss(caplog: pytest.LogCaptureFixture) -> bool:
    lost = losses(caplog)
    return len(lost) == 1 and lost[0].levelno == logging.ERROR and "request-1" in lost[0].getMessage()


def test_a_handler_running_past_its_lease_is_renewed_then_its_outcome_answers(
    store, caplog: pytest.LogCaptureFixture
) -> None:
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

    with caplog.at_level(logging.WARNING, logger="request_replay.renewal"):
        asyncio.run(scenario())
    assert not losses(caplog)

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
    assert replay.renew(attempt) is None

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert (row.outcome, row.lease_until, row.lease_owner) == (OUTCOME, None, None)


def test_a_renewal_before_the_record_leaves_the_outcome_and_no_lease(store) -> None:
    clock = ManualClock()
    replay, attempt = _recorded_attempt(store, clock)

    clock.advance(10)
    assert replay.renew(attempt) == START + 10 + POLICY.lease_seconds
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


class RefusesEveryRenewal:
    """A store that refuses every renewal, as under a write lock held past the lease."""

    def __init__(self, store: object) -> None:
        self._store = store

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def renew(self, *args: object, **kwargs: object) -> bool:
        raise sqlite3.OperationalError("database is locked")


def test_a_lease_never_renewed_ends_under_a_live_handler_and_its_loss_is_logged(
    store, caplog: pytest.LogCaptureFixture
) -> None:
    clock = ManualClock()
    replay = guard(RefusesEveryRenewal(store), clock)
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
        with caplog.at_level(logging.WARNING, logger="request_replay.renewal"):
            clock.advance(10)
            await sleep.step()
            clock.advance(10)
            await sleep.step()
            assert not losses(caplog)
            clock.advance(10)
            await sleep.last_step()
            await asyncio.sleep(0)
        # The residual case: the attempt still runs, and its retry is told the
        # outcome is unknown.
        assert not running.done()
        assert replay.admit(request) == OutcomeUnknown()
        assert logged_one_loss(caplog)
        assert len(sleep.asked) == 3  # it stopped renewing
        finish.set()
        await asyncio.wait_for(running, STEP_BOUND)

    asyncio.run(scenario())


def test_a_lease_ending_between_renewals_is_logged_when_the_handler_returns(
    store, caplog: pytest.LogCaptureFixture
) -> None:
    clock = ManualClock()
    replay = guard(RefusesEveryRenewal(store), clock)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(entry(Resolution.RECORDED))
        assert isinstance(first, Dispatch)
        with caplog.at_level(logging.WARNING, logger="request_replay.renewal"):
            async with renewing(replay, first.attempt, sleep=sleep):
                clock.advance(10)
                await sleep.step()
                clock.advance(POLICY.lease_seconds)
            assert logged_one_loss(caplog)

    asyncio.run(scenario())


def test_a_renewal_that_finds_its_lease_ended_logs_the_loss(store, caplog: pytest.LogCaptureFixture) -> None:
    clock = ManualClock()
    replay = guard(store, clock)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(entry(Resolution.RECORDED))
        assert isinstance(first, Dispatch)
        renewal = Renewal.start(replay, first.attempt, sleep=sleep)
        # A stalled loop, or a time source moved, ends the lease before a renewal.
        clock.advance(POLICY.lease_seconds)
        with caplog.at_level(logging.WARNING, logger="request_replay.renewal"):
            await sleep.last_step()
            await asyncio.sleep(0)
            assert logged_one_loss(caplog)
            assert sleep.asked == [POLICY.lease_seconds / 3]  # it stopped renewing
            await renewal.stop()
        assert logged_one_loss(caplog)

    asyncio.run(scenario())


def test_a_started_renewal_renews_until_it_is_stopped(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    request = entry(Resolution.RECORDED)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(request)
        assert isinstance(first, Dispatch)
        renewal = Renewal.start(replay, first.attempt, sleep=sleep)
        clock.advance(10)
        await sleep.step()
        clock.advance(25)
        assert replay.admit(request) == InProgress()
        await renewal.stop()
        assert all(task is asyncio.current_task() for task in asyncio.all_tasks())

    asyncio.run(scenario())


def test_a_cancelled_renewal_writes_nothing_more(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    request = entry(Resolution.RECORDED)

    async def scenario() -> None:
        sleep = SteppedSleep()
        first = replay.admit(request)
        assert isinstance(first, Dispatch)
        renewal = Renewal.start(replay, first.attempt, sleep=sleep)
        clock.advance(10)
        await sleep.step()
        renewal.cancel()
        await asyncio.sleep(0)
        assert all(task is asyncio.current_task() for task in asyncio.all_tasks())

    asyncio.run(scenario())

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert row.lease_until == START + 10 + POLICY.lease_seconds
