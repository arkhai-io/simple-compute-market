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


async def _settle(cycles: int = 5) -> None:
    for _ in range(cycles):
        await asyncio.sleep(0.005)


def _stale_database(tmp_path) -> str:
    path = str(tmp_path / "threads.db")
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _database(path, [("stale-1", old, None)])
    return path


@pytest.mark.asyncio
async def test_a_pause_requested_during_the_wait_holds_the_next_sweep(tmp_path):
    """The gate is the last read before a sweep, not the first read of a cycle.

    A pause requested while the loop waits out its interval must stop the next
    sweep; a loop that gated before its wait and swept after it would sweep once
    more with the pause already requested.
    """
    repository = Repository(_stale_database(tmp_path))
    loops = StorefrontLoopController()
    policy = NegotiationWatchdogPolicy(
        timeout_seconds=60, interval_seconds=0.05, initial_delay_seconds=0
    )
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
    try:
        await _settle(2)
        assert loops.states() == {"negotiation_watchdog": "running"}
        await loops.pause()
        await asyncio.sleep(0.2)
        assert repository.updates == [], "a held watchdog swept"

        await loops.resume()
        await asyncio.wait_for(_until(lambda: bool(repository.updates)), timeout=1)
        assert repository.updates == [("stale-1", "abandoned")]
    finally:
        loops.clear_loops()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_a_long_interval_does_not_delay_the_pause(tmp_path):
    """The gate is read on entry and the wait wakes on a pause request, so a
    pause quiesces within its bound however long the interval is."""
    repository = Repository(_stale_database(tmp_path))
    loops = StorefrontLoopController(quiescence_timeout=1.0)
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
    try:
        await _settle(1)
        assert await loops.pause() == {"negotiation_watchdog": "paused"}
        assert repository.updates == []
    finally:
        loops.clear_loops()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_a_failing_sweep_still_waits_its_interval(tmp_path, caplog):
    """A sweep that raises must not turn the loop into a tight retry."""
    repository = Repository(str(tmp_path / "missing-table.db"))
    waits: list[float] = []

    async def _wait(seconds: float) -> None:
        waits.append(seconds)
        await asyncio.sleep(0.005)

    policy = NegotiationWatchdogPolicy(
        timeout_seconds=60, interval_seconds=0.001, initial_delay_seconds=0
    )
    task = asyncio.create_task(
        run_negotiation_watchdog(repository, policy, wait=_wait)
    )
    with caplog.at_level("ERROR"):
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    failures = [r for r in caplog.records if "negotiation_watchdog_loop error" in r.getMessage()]
    assert failures, "the sweep was expected to fail against a missing table"
    assert len(failures) <= len(waits) + 1


async def _until(predicate) -> None:
    while not predicate():
        await asyncio.sleep(0.005)
