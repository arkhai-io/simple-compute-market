from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
from market_storefront_kit import (
    NegotiationWatchdogPolicy,
    StorefrontLoopController,
    run_negotiation_watchdog,
    sweep_stale_negotiations,
)


@dataclass
class Repository:
    db_path: str
    updates: list[tuple[str, str]] = field(default_factory=list)
    fail: frozenset[str] = frozenset()

    async def update_negotiation_thread_terminal(
        self,
        *,
        negotiation_id: str,
        terminal_state: str,
    ) -> None:
        if negotiation_id in self.fail:
            raise RuntimeError("write failed")
        self.updates.append((negotiation_id, terminal_state))
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE negotiation_threads SET terminal_state = ? "
                "WHERE negotiation_id = ?",
                (terminal_state, negotiation_id),
            )
            connection.commit()
        finally:
            connection.close()


def _database(path: str, rows: list[tuple[str, str, str | None]]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """CREATE TABLE negotiation_threads (
                 negotiation_id TEXT PRIMARY KEY,
                 our_listing_id TEXT,
                 updated_at TEXT NOT NULL,
                 terminal_state TEXT
               )"""
        )
        connection.executemany(
            "INSERT INTO negotiation_threads VALUES (?, 'listing-1', ?, ?)",
            rows,
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.asyncio
async def test_sweep_marks_only_stale_active_threads_and_emits_domain_event(tmp_path):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    old = (now - timedelta(hours=2)).isoformat()
    recent = (now - timedelta(minutes=1)).isoformat()
    db_path = str(tmp_path / "storefront.db")
    _database(
        db_path,
        [
            ("stale", old, None),
            ("fresh", recent, None),
            ("terminal", old, "success"),
        ],
    )
    repository = Repository(db_path)
    events: list[dict[str, object]] = []

    count = await sweep_stale_negotiations(
        repository,
        NegotiationWatchdogPolicy(
            timeout_seconds=1800,
            interval_seconds=60,
        ),
        emit_stage_event=lambda **fields: events.append(fields),
        now=now,
    )

    assert count == 1
    assert repository.updates == [("stale", "abandoned")]
    assert events == [
        {
            "stage": "negotiation",
            "event": "abandoned",
            "negotiation_id": "stale",
            "order_id": "listing-1",
            "reason": "watchdog_timeout",
            "updated_at": old,
        }
    ]


@pytest.mark.asyncio
async def test_sweep_isolates_one_failed_terminal_update(tmp_path):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    old = (now - timedelta(hours=2)).isoformat()
    db_path = str(tmp_path / "storefront.db")
    _database(db_path, [("fails", old, None), ("succeeds", old, None)])
    repository = Repository(db_path, fail=frozenset({"fails"}))

    count = await sweep_stale_negotiations(
        repository,
        NegotiationWatchdogPolicy(
            timeout_seconds=1800,
            interval_seconds=60,
            terminal_state="expired",
        ),
        now=now,
    )

    assert count == 2
    assert repository.updates == [("succeeds", "expired")]


def test_policy_rejects_non_positive_schedules():
    with pytest.raises(ValueError, match="timeout"):
        NegotiationWatchdogPolicy(timeout_seconds=0, interval_seconds=60)
    with pytest.raises(ValueError, match="interval"):
        NegotiationWatchdogPolicy(timeout_seconds=1, interval_seconds=0)


class _Control:
    """A gate and an interruptible wait, driven by the test.

    The wait never expires on its own: it returns when the test ticks it or a
    pause is requested, so each tick lets the runner through exactly one more
    cycle and nothing here waits on time. Gate reads are counted, so a test can
    wait for a held runner to have re-read its gate.
    """

    def __init__(self) -> None:
        self.paused = False
        self.signal = asyncio.Event()
        self.tick = asyncio.Event()
        self.waiting = asyncio.Event()
        self.waits = 0
        self.held_reads = 0
        self._held_read = asyncio.Event()

    def gate(self) -> bool:
        if self.paused:
            self.held_reads += 1
            self._held_read.set()
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
        """Let the runner through one cycle and back into its wait."""
        self.waiting.clear()
        self.tick.set()
        await asyncio.wait_for(self.waiting.wait(), timeout=1)

    async def held_reads_reach(self, count: int) -> None:
        while self.held_reads < count:
            self._held_read.clear()
            await asyncio.wait_for(self._held_read.wait(), timeout=1)

    def pause(self) -> None:
        self.paused = True
        self.signal.set()

    def resume(self) -> None:
        self.paused = False
        self.signal.clear()


def _stale(at_hours: float = 2.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=at_hours)).isoformat()


def _insert(path: str, negotiation_id: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO negotiation_threads VALUES (?, 'listing-1', ?, NULL)",
            (negotiation_id, _stale()),
        )
        connection.commit()
    finally:
        connection.close()


async def _stop(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


#: An interval short enough that a sweep is always due by the next cycle. The
#: test, not the clock, decides when a cycle runs: the injected wait returns only
#: when ticked or paused.
_DUE = 1e-6


@pytest.mark.asyncio
async def test_a_pause_requested_during_the_wait_holds_the_next_sweep(tmp_path):
    """The gate is the last read before a sweep, not the first read of a cycle.

    A pause requested while the runner waits out its interval must stop the next
    sweep; a runner that gated before its wait and swept after it would sweep once
    more with the pause already requested.
    """
    path = str(tmp_path / "threads.db")
    _database(path, [("stale-1", _stale(), None)])
    repository = Repository(path)
    control = _Control()
    policy = NegotiationWatchdogPolicy(
        timeout_seconds=60, interval_seconds=_DUE, initial_delay_seconds=0
    )
    runner = asyncio.create_task(
        run_negotiation_watchdog(repository, policy, paused=control.gate, wait=control.wait)
    )
    try:
        await asyncio.wait_for(control.waiting.wait(), timeout=1)
        await control.next_wait()
        assert repository.updates == [("stale-1", "abandoned")]

        _insert(path, "stale-2")
        control.pause()
        await control.held_reads_reach(3)
        assert repository.updates == [("stale-1", "abandoned")], "a held watchdog swept"

        control.resume()
        await control.next_wait()
        assert repository.updates[-1] == ("stale-2", "abandoned")
    finally:
        await _stop(runner)


@pytest.mark.asyncio
async def test_a_long_interval_does_not_delay_the_pause(tmp_path):
    """The gate is read on entry and the controller's wait wakes on a pause
    request, so a pause quiesces at once however long the interval is."""
    path = str(tmp_path / "threads.db")
    _database(path, [("stale-1", _stale(), None)])
    repository = Repository(path)
    loops = StorefrontLoopController()
    policy = NegotiationWatchdogPolicy(timeout_seconds=60, interval_seconds=3600)
    loops.start_loop(
        StorefrontBackgroundTask(
            name="negotiation_watchdog",
            task_factory=partial(
                run_negotiation_watchdog,
                repository,
                policy,
                paused=loops.loop_gate("negotiation_watchdog"),
                wait=loops.idle,
            ),
        )
    )
    handles = list(loops._handles.values())
    try:
        states = await asyncio.wait_for(loops.pause(), timeout=1)
        assert states == {"negotiation_watchdog": "paused"}
        assert repository.updates == []
    finally:
        loops.clear_loops()
        await asyncio.gather(*handles, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_failing_sweep_still_waits_its_interval(tmp_path, caplog):
    """A sweep that raises must not turn the runner into a tight retry: each
    failure is followed by a wait."""
    repository = Repository(str(tmp_path / "missing-table.db"))
    control = _Control()
    policy = NegotiationWatchdogPolicy(
        timeout_seconds=60, interval_seconds=_DUE, initial_delay_seconds=0
    )
    with caplog.at_level("ERROR"):
        runner = asyncio.create_task(
            run_negotiation_watchdog(repository, policy, paused=control.gate, wait=control.wait)
        )
        try:
            await asyncio.wait_for(control.waiting.wait(), timeout=1)
            for _ in range(3):
                await control.next_wait()
        finally:
            await _stop(runner)
    failures = [r for r in caplog.records if "negotiation_watchdog_loop error" in r.getMessage()]
    assert failures, "the sweep was expected to fail against a missing table"
    assert len(failures) <= control.waits


@pytest.mark.asyncio
async def test_a_gated_watchdog_without_an_interruptible_wait_is_refused(tmp_path):
    policy = NegotiationWatchdogPolicy(timeout_seconds=60, interval_seconds=3600)
    with pytest.raises(TypeError):
        await run_negotiation_watchdog(
            Repository(str(tmp_path / "threads.db")), policy, paused=lambda: False
        )
