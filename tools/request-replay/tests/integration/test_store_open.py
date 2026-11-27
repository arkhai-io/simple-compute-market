"""Opening a store issues no DDL, and its rows outlive it."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError as SqlAlchemyOperationalError

from request_replay import Answered, Dispatch, Resolution, SqliteReplayStore, StoreUnavailable
from request_replay.sqlalchemy_store import SqlAlchemyReplayStore

from tests.support import OUTCOME, ManualClock, entry, guard


def schema(path: Path) -> list[tuple[str, str, str]]:
    connection = sqlite3.connect(path)
    try:
        return sorted(connection.execute("SELECT type, name, sql FROM sqlite_master").fetchall())
    finally:
        connection.close()


def test_opening_and_using_a_store_changes_no_schema(database: Path, make_store: Callable[[], object]) -> None:
    before = schema(database)
    assert [name for _, name, _ in before if not name.startswith("sqlite_")] == [
        "ix_request_replay_expires_at",
        "request_replay",
    ]

    store = make_store()
    replay = guard(store, ManualClock())
    first = replay.admit(entry(Resolution.RECORDED))
    assert isinstance(first, Dispatch)
    replay.complete(first.attempt, OUTCOME)
    replay.sweep()

    assert schema(database) == before


def test_a_store_over_a_database_without_its_table_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite3"
    sqlite3.connect(path).close()
    engine = create_engine(f"sqlite:///{path}")
    try:
        sqlite_store = SqliteReplayStore(lambda: sqlite3.connect(path))
        engine_store = SqlAlchemyReplayStore(engine)

        with pytest.raises(StoreUnavailable, match="no such table") as from_sqlite:
            guard(sqlite_store, ManualClock()).admit(entry(Resolution.RERUN))
        with pytest.raises(StoreUnavailable, match="no such table") as from_engine:
            guard(engine_store, ManualClock()).admit(entry(Resolution.RERUN))
        assert isinstance(from_sqlite.value.__cause__, sqlite3.OperationalError)
        assert isinstance(from_engine.value.__cause__, SqlAlchemyOperationalError)
    finally:
        engine.dispose()

    assert schema(path) == []


def test_a_recorded_response_outlives_the_store_that_recorded_it(make_store: Callable[[], object]) -> None:
    clock = ManualClock()
    replay = guard(make_store(), clock)
    first = replay.admit(entry(Resolution.RECORDED))
    assert isinstance(first, Dispatch)
    replay.complete(first.attempt, OUTCOME)

    restarted = guard(make_store(), clock)

    assert restarted.admit(entry(Resolution.RECORDED)) == Answered(OUTCOME)
