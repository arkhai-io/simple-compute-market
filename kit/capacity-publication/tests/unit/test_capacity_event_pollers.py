"""The aggregate capacity-event loop holds while gated and surfaces a failed fan-out,
each site's cycle is serialized with that site's step, and each site's poller
reports every cycle it ran.

The aggregate's cadence is the injected wait, which the test drives: each wait
parks until the test ticks it or a pause is requested. Nothing here waits on time.
"""

from __future__ import annotations

import asyncio

import pytest

from core_storefront.aggregation import fill_first
from market_capacity_publication import CapacityRuntime, CapacitySite, run_capacity_event_pollers
from market_capacity_publication.capacity_remote import (
    reset_site_event_cursors,
    site_event_cursor,
    site_events_poller,
)


class _Control:
    """A gate and an interruptible wait standing in for a loop controller."""

    def __init__(self) -> None:
        self.paused = False
        self.signal = asyncio.Event()
        self.tick = asyncio.Event()
        self.waiting = asyncio.Event()
        self.acknowledged = asyncio.Event()
        self.waits = 0

    def gate(self) -> bool:
        if self.paused:
            self.acknowledged.set()
        return self.paused

    async def wait(self, seconds: float) -> None:
        self.waits += 1
        self.waiting.set()
        tick = asyncio.ensure_future(self.tick.wait())
        pause = asyncio.ensure_future(self.signal.wait())
        try:
            await asyncio.wait({tick, pause}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            tick.cancel()
            pause.cancel()
        self.tick.clear()

    async def next_wait(self) -> None:
        """Release the aggregate from its wait and let it return to the next one."""
        self.waiting.clear()
        self.tick.set()
        await asyncio.wait_for(self.waiting.wait(), timeout=1)

    def pause(self) -> None:
        self.paused = True
        self.signal.set()


def _site_gate(site_id):
    return lambda: False


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_the_fan_out_receives_the_site_gates_and_wait_and_is_cancelled_on_exit():
    received = {}
    started = asyncio.Event()
    cancelled = asyncio.Event()
    control = _Control()

    async def _poll_events(*, paused, wait):
        received.update(paused=paused, wait=wait)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=control.gate, site_gate=_site_gate, wait=control.wait
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await _stop(task)

    assert received == {"paused": _site_gate, "wait": control.wait}
    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_a_failed_fan_out_ends_the_aggregate_loop():
    control = _Control()
    failed = asyncio.Event()

    async def _poll_events(*, paused, wait):
        failed.set()
        raise RuntimeError("authority unreachable")

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=control.gate, site_gate=_site_gate, wait=control.wait
        )
    )
    await asyncio.wait_for(failed.wait(), timeout=1)
    await asyncio.wait_for(control.waiting.wait(), timeout=1)
    control.tick.set()

    with pytest.raises(RuntimeError, match="authority unreachable"):
        await asyncio.wait_for(task, timeout=1)


async def test_a_gated_aggregate_does_not_surface_the_fan_out_until_released():
    gate_reads: list[bool] = []
    held = {"value": True}
    read_twice = asyncio.Event()
    control = _Control()

    def _gate() -> bool:
        gate_reads.append(held["value"])
        if len(gate_reads) >= 2:
            read_twice.set()
        return held["value"]

    async def _poll_events(*, paused, wait):
        raise RuntimeError("authority unreachable")

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=_gate, site_gate=_site_gate, wait=control.wait
        )
    )
    try:
        await asyncio.wait_for(read_twice.wait(), timeout=1)
        assert not task.done(), "a held aggregate loop acted on its fan-out"
        assert all(gate_reads)
    finally:
        held["value"] = False

    with pytest.raises(RuntimeError):
        await asyncio.wait_for(task, timeout=1)


async def test_a_storefront_with_no_site_keeps_its_aggregate_loop_alive():
    control = _Control()

    async def _poll_events(*, paused, wait):
        return None

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events, gate=control.gate, site_gate=_site_gate, wait=control.wait
        )
    )
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        await control.next_wait()
        await control.next_wait()
        assert not task.done()
    finally:
        await _stop(task)


async def test_a_pause_reaches_the_aggregate_through_its_wait():
    """However long the aggregate's cadence, a pause requested while it waits
    reaches its gate at once."""
    control = _Control()

    async def _poll_events(*, paused, wait):
        await asyncio.Event().wait()

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events,
            gate=control.gate,
            site_gate=_site_gate,
            wait=control.wait,
            gate_seconds=3600,
        )
    )
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        control.pause()
        await asyncio.wait_for(control.acknowledged.wait(), timeout=1)
    finally:
        await _stop(task)


class _ParkedFeed:
    """One site's event feed, whose first read parks until the test releases it.

    Every read is logged as it starts and as it returns, so the log shows
    whether two cycles of this site ever read the feed at once.
    """

    def __init__(self, site_id: str, log: list[tuple[str, str]]) -> None:
        self.base_url = f"http://{site_id}.invalid"
        self.site_id = site_id
        self.log = log
        self.reads = 0
        self.first_read_started = asyncio.Event()
        self.release_first_read = asyncio.Event()

    async def events_after(self, after: int, limit: int | None = None):
        index = self.reads
        self.reads += 1
        self.log.append((self.site_id, "start"))
        if index == 0:
            self.first_read_started.set()
            await self.release_first_read.wait()
        self.log.append((self.site_id, "end"))
        return [], after


async def _no_reconcile(context) -> None:
    return None


class _ObservedLock(asyncio.Lock):
    """A site's cursor lock, reporting each attempt to acquire it.

    Lets a test wait until a cycle is actually waiting on the lock, rather than
    yielding and hoping it got there.
    """

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0
        self._attempted = asyncio.Event()

    async def acquire(self) -> bool:
        self.attempts += 1
        self._attempted.set()
        return await super().acquire()

    async def attempts_reach(self, count: int) -> None:
        while self.attempts < count:
            self._attempted.clear()
            await asyncio.wait_for(self._attempted.wait(), timeout=1)


@pytest.fixture
def _fresh_cursors():
    reset_site_event_cursors()
    yield
    reset_site_event_cursors()


def _runtime_over(feeds: dict[str, _ParkedFeed]) -> CapacityRuntime:
    runtime = CapacityRuntime(
        sites=[CapacitySite(site, f"http://{site}.invalid", None) for site in feeds],
        signer=object(),
        placement=fill_first,
        reconcile=_no_reconcile,
        site_client_factory=lambda site, signer: feeds[site.site_id],
    )
    # Positioned, so a cycle reads the feed once and runs no full reconcile.
    for site in feeds:
        site_event_cursor(site).last_applied = 1
    return runtime


async def _park(seconds: float) -> None:
    await asyncio.Event().wait()


async def test_a_sites_step_waits_for_that_sites_poll_and_not_for_another_sites(
    _fresh_cursors,
):
    log: list[tuple[str, str]] = []
    feeds = {site: _ParkedFeed(site, log) for site in ("east", "west")}
    runtime = _runtime_over(feeds)
    east_lock = site_event_cursor("east").lock = _ObservedLock()

    pollers = asyncio.create_task(
        runtime.poll_events(interval_seconds=60, paused=None, wait=_park)
    )
    try:
        await asyncio.wait_for(feeds["east"].first_read_started.wait(), timeout=1)
        await asyncio.wait_for(feeds["west"].first_read_started.wait(), timeout=1)
        feeds["west"].release_first_read.set()

        # West's poll has finished, so west's step runs while east's poll is
        # still parked in its read.
        west = await asyncio.wait_for(runtime.drain_events_once("west"), timeout=1)
        assert west.error is None

        east_step = asyncio.create_task(runtime.drain_events_once("east"))
        await east_lock.attempts_reach(2)
        assert feeds["east"].reads == 1, "east's step read the feed during east's poll"

        feeds["east"].release_first_read.set()
        east = await asyncio.wait_for(east_step, timeout=1)
        assert east.error is None
        east_log = [entry for site, entry in log if site == "east"]
        assert east_log == ["start", "end", "start", "end"]
    finally:
        pollers.cancel()
        await asyncio.gather(pollers, return_exceptions=True)


async def test_a_poller_held_while_it_waited_on_a_step_runs_no_cycle(_fresh_cursors):
    """The poller reads its gate again under the site's lock, immediately before
    any request, so a pause requested while it waited for a step holds it."""
    log: list[tuple[str, str]] = []
    feed = _ParkedFeed("east", log)
    runtime = _runtime_over({"east": feed})
    lock = site_event_cursor("east").lock = _ObservedLock()
    held = {"value": False}
    gate_reads: list[bool] = []
    read_held = asyncio.Event()

    def _gate() -> bool:
        gate_reads.append(held["value"])
        if held["value"]:
            read_held.set()
        return held["value"]

    step = asyncio.create_task(runtime.drain_events_once("east"))
    await asyncio.wait_for(feed.first_read_started.wait(), timeout=1)
    poller = asyncio.create_task(
        site_events_poller(
            runtime.client(),
            "east",
            feed,
            60,
            full_reconcile=runtime.reconcile_now,
            paused=_gate,
            wait=_park,
        )
    )
    try:
        await lock.attempts_reach(2)
        assert gate_reads == [False]

        held["value"] = True
        feed.release_first_read.set()
        await asyncio.wait_for(step, timeout=1)
        await asyncio.wait_for(read_held.wait(), timeout=1)

        assert feed.reads == 1, "the held poller read the feed after the step"
    finally:
        poller.cancel()
        await asyncio.gather(poller, return_exceptions=True)


class _Feed:
    """One site's event feed, failing its reads while ``failing`` is set."""

    def __init__(self, site_id: str) -> None:
        self.base_url = f"http://{site_id}.invalid"
        self.failing: Exception | None = None

    async def events_after(self, after: int, limit: int | None = None):
        if self.failing is not None:
            raise self.failing
        return [], after


class _Recorder:
    """Where each site's poller reports the cycles it ran, by site."""

    def __init__(self) -> None:
        self.cycles: dict[str, list] = {}
        self.reported = asyncio.Event()

    def __call__(self, site_id: str):
        def record(cycle) -> None:
            self.cycles.setdefault(site_id, []).append(cycle)
            self.reported.set()

        return record

    async def next_report(self) -> None:
        self.reported.clear()
        await asyncio.wait_for(self.reported.wait(), timeout=1)


async def test_each_sites_poller_reports_every_cycle_it_ran_with_any_failure(_fresh_cursors):
    """A failed cycle is reported with the exception that ended it, so its
    outcome can be recorded by type; another site's cycles are its own."""
    feeds = {"east": _Feed("east"), "west": _Feed("west")}
    refused = ConnectionError("http://east.invalid refused the connection")
    feeds["east"].failing = refused
    runtime = CapacityRuntime(
        sites=[CapacitySite(site, f"http://{site}.invalid", None) for site in feeds],
        signer=object(),
        placement=fill_first,
        reconcile=_no_reconcile,
        site_client_factory=lambda site, signer: feeds[site.site_id],
    )
    for site in feeds:
        site_event_cursor(site).last_applied = 1
    recorder = _Recorder()
    control = _Control()

    pollers = asyncio.create_task(
        runtime.poll_events(
            interval_seconds=60, paused=None, wait=control.wait, record=recorder
        )
    )
    try:
        while set(recorder.cycles) != {"east", "west"}:
            await recorder.next_report()
        (east,) = recorder.cycles["east"]
        (west,) = recorder.cycles["west"]
        assert east.exception is refused
        assert east.error == str(refused)
        assert "exception" not in east.to_dict()
        assert west.exception is None and west.error is None
    finally:
        pollers.cancel()
        await asyncio.gather(pollers, return_exceptions=True)


async def test_a_held_poller_reports_no_cycle(_fresh_cursors):
    feed = _Feed("east")
    runtime = CapacityRuntime(
        sites=[CapacitySite("east", "http://east.invalid", None)],
        signer=object(),
        placement=fill_first,
        reconcile=_no_reconcile,
        site_client_factory=lambda site, signer: feed,
    )
    site_event_cursor("east").last_applied = 1
    recorder = _Recorder()
    gate_reads = asyncio.Event()

    def held() -> bool:
        gate_reads.set()
        return True

    poller = asyncio.create_task(
        site_events_poller(
            runtime.client(),
            "east",
            feed,
            60,
            full_reconcile=runtime.reconcile_now,
            paused=held,
            wait=_park,
            record=recorder("east"),
        )
    )
    try:
        await asyncio.wait_for(gate_reads.wait(), timeout=1)
        # A step for the held site still runs, and is the step's to report.
        cycle = await asyncio.wait_for(runtime.drain_events_once("east"), timeout=1)
        assert cycle.error is None
        assert recorder.cycles == {}
    finally:
        poller.cancel()
        await asyncio.gather(poller, return_exceptions=True)


async def test_the_aggregate_hands_each_site_where_its_cycles_are_reported():
    received = {}
    started = asyncio.Event()
    control = _Control()
    recorder = _Recorder()

    async def _poll_events(*, paused, wait, record):
        received.update(paused=paused, wait=wait, record=record)
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        run_capacity_event_pollers(
            _poll_events,
            gate=control.gate,
            site_gate=_site_gate,
            wait=control.wait,
            record_site_cycle=recorder,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    await _stop(task)

    assert received == {"paused": _site_gate, "wait": control.wait, "record": recorder}
