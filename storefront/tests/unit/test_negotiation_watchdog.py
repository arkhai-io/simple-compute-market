"""Unit tests for the negotiation watchdog.

Watchdog invariants:
  1. A thread with terminal_state NULL + updated_at older than the
     configured timeout gets marked `terminal_state='abandoned'`.
  2. Threads younger than the timeout are left alone.
  3. Threads already in a terminal state are ignored.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from market_storefront.negotiation_watchdog import _watchdog_tick
from market_storefront.utils.sqlite_client import SQLiteClient


def _init_threads_table(db_path: str) -> None:
    """Create the minimal negotiation_threads schema + run migrations."""
    # Initialising SQLiteClient triggers the `_ensure_tables` migrations,
    # which create the full schema we need.
    SQLiteClient(db_path=db_path)


def _insert_thread(
    db_path: str,
    *,
    negotiation_id: str,
    updated_at: str,
    terminal_state: str | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO negotiation_threads
               (negotiation_id, our_order_id, their_order_id,
                our_agent_id, their_agent_id, status,
                created_at, updated_at, terminal_state)
               VALUES (?, 'o1', 'o2', 'a1', 'a2', 'active', ?, ?, ?)""",
            (negotiation_id, updated_at, updated_at, terminal_state),
        )
        conn.commit()
    finally:
        conn.close()


def _read_terminal_state(db_path: str, negotiation_id: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT terminal_state FROM negotiation_threads WHERE negotiation_id = ?",
            (negotiation_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_stale_active_thread_is_abandoned(tmp_path):
    """A 2-hour-old active thread with a 30-minute timeout → abandoned."""
    db_path = str(tmp_path / "agent.db")
    _init_threads_table(db_path)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _insert_thread(db_path, negotiation_id="neg-stale-001", updated_at=old_ts)

    client = SQLiteClient(db_path=db_path)
    with patch("market_storefront.negotiation_watchdog.CONFIG") as cfg:
        cfg.negotiation_timeout_seconds = 1800  # 30 min
        n = await _watchdog_tick(client)

    assert n == 1, f"Expected 1 abandoned, got {n}"
    assert _read_terminal_state(db_path, "neg-stale-001") == "abandoned"


@pytest.mark.asyncio
async def test_fresh_active_thread_is_left_alone(tmp_path):
    """A 1-minute-old active thread with a 30-minute timeout → still active."""
    db_path = str(tmp_path / "agent.db")
    _init_threads_table(db_path)
    recent_ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _insert_thread(db_path, negotiation_id="neg-fresh-001", updated_at=recent_ts)

    client = SQLiteClient(db_path=db_path)
    with patch("market_storefront.negotiation_watchdog.CONFIG") as cfg:
        cfg.negotiation_timeout_seconds = 1800
        n = await _watchdog_tick(client)

    assert n == 0
    assert _read_terminal_state(db_path, "neg-fresh-001") is None


@pytest.mark.asyncio
async def test_already_terminal_thread_is_not_re_marked(tmp_path):
    """Threads that already have a terminal_state are ignored (idempotent)."""
    db_path = str(tmp_path / "agent.db")
    _init_threads_table(db_path)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _insert_thread(
        db_path, negotiation_id="neg-done-001",
        updated_at=old_ts, terminal_state="success",
    )

    client = SQLiteClient(db_path=db_path)
    with patch("market_storefront.negotiation_watchdog.CONFIG") as cfg:
        cfg.negotiation_timeout_seconds = 1800
        n = await _watchdog_tick(client)

    assert n == 0
    assert _read_terminal_state(db_path, "neg-done-001") == "success"


@pytest.mark.asyncio
async def test_mixed_threads_only_stale_active_abandoned(tmp_path):
    """Given stale-active + fresh-active + already-terminal, only the first is touched."""
    db_path = str(tmp_path / "agent.db")
    _init_threads_table(db_path)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    recent_ts = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _insert_thread(db_path, negotiation_id="stale-a", updated_at=old_ts)
    _insert_thread(db_path, negotiation_id="stale-b", updated_at=old_ts)
    _insert_thread(db_path, negotiation_id="fresh-c", updated_at=recent_ts)
    _insert_thread(
        db_path, negotiation_id="done-d",
        updated_at=old_ts, terminal_state="failure",
    )

    client = SQLiteClient(db_path=db_path)
    with patch("market_storefront.negotiation_watchdog.CONFIG") as cfg:
        cfg.negotiation_timeout_seconds = 1800
        n = await _watchdog_tick(client)

    assert n == 2
    assert _read_terminal_state(db_path, "stale-a") == "abandoned"
    assert _read_terminal_state(db_path, "stale-b") == "abandoned"
    assert _read_terminal_state(db_path, "fresh-c") is None
    assert _read_terminal_state(db_path, "done-d") == "failure"
