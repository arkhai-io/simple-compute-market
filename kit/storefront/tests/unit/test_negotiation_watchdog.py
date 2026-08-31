from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from market_storefront_kit import (
    NegotiationWatchdogPolicy,
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
