"""A retry is told the outcome is unknown only after the attempt's own transaction ends.

Library integration on both stores over one real SQLite file, which the attempt's
"handler" also writes: the handler holds its write transaction past its lease, and
its exact retry must not be answered ``OutcomeUnknown`` while that transaction is
open. The stores meet the held lock with no busy timeout, so the retry is refused
at once rather than after a wait.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from request_replay import Answered, Dispatch, OutcomeUnknown, Resolution, SqliteReplayStore, StoreUnavailable
from request_replay.sqlalchemy_store import SqlAlchemyReplayStore

from tests.support import OUTCOME, POLICY, ManualClock, entry, guard

LEASE = POLICY.lease_seconds
SKEW = POLICY.skew_seconds


@pytest.fixture
def unwaiting_store(database: Path, store_kind: str) -> Iterator[object]:
    """A store over ``database`` that meets a held write lock with no busy timeout."""

    if store_kind == "sqlite3":
        yield SqliteReplayStore(lambda: sqlite3.connect(database, timeout=0))
        return
    engine = create_engine(f"sqlite:///{database}", connect_args={"timeout": 0})
    yield SqlAlchemyReplayStore(engine)
    engine.dispose()


@pytest.fixture
def items(database: Path) -> Path:
    _execute(database, "CREATE TABLE items (item TEXT PRIMARY KEY, value INTEGER NOT NULL)")
    return database


def _execute(database: Path, statement: str) -> None:
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        connection.execute(statement)


def _one(database: Path, query: str) -> object:
    with closing(sqlite3.connect(database, isolation_level=None)) as reader:
        row = reader.execute(query).fetchone()
    return None if row is None else row[0]


class Handler:
    """The attempt's handler, holding one write transaction on the database."""

    def __init__(self, database: Path) -> None:
        self._connection = sqlite3.connect(database, isolation_level=None)

    def begin_writing(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        self._connection.execute("INSERT INTO items (item, value) VALUES ('a', 1)")

    def commit(self) -> None:
        self._connection.execute("COMMIT")

    def close(self) -> None:
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK")
        self._connection.close()


@pytest.fixture
def handler(items: Path) -> Iterator[Handler]:
    held = Handler(items)
    yield held
    held.close()


# A retry within the skew finds the row through the store's claim; one older than
# the skew through a read, which on the SQLAlchemy store is a plain read a write
# lock does not stop, so only its concluding write meets the lock.
@pytest.mark.parametrize("waited", [LEASE, SKEW + 1], ids=["within-the-skew", "older-than-the-skew"])
def test_a_retry_is_refused_while_the_handlers_transaction_is_open_then_concludes_it(
    items: Path, handler: Handler, unwaiting_store: object, waited: int
) -> None:
    clock = ManualClock()
    replay = guard(unwaiting_store, clock)
    request = entry(Resolution.RECORDED)
    first = replay.admit(request)
    assert isinstance(first, Dispatch)

    handler.begin_writing()
    clock.advance(waited)
    with pytest.raises(StoreUnavailable, match="locked"):
        replay.admit(request)
    assert _one(items, "SELECT lease_until FROM request_replay") == first.attempt.lease_until
    handler.commit()

    assert replay.admit(request) == OutcomeUnknown()
    assert _one(items, "SELECT value FROM items WHERE item = 'a'") == 1
    _execute(items, "UPDATE items SET value = 2 WHERE item = 'a'")
    # The attempt's late completion records its answer and touches no domain row.
    replay.complete(first.attempt, OUTCOME)

    assert _one(items, "SELECT value FROM items WHERE item = 'a'") == 2
    assert replay.admit(request) == Answered(OUTCOME)


def test_a_retry_of_a_concluded_attempt_still_waits_for_a_held_transaction(
    items: Path, handler: Handler, unwaiting_store: object
) -> None:
    clock = ManualClock()
    replay = guard(unwaiting_store, clock)
    request = entry(Resolution.RECORDED)
    assert isinstance(replay.admit(request), Dispatch)
    clock.advance(SKEW + 1)
    assert replay.admit(request) == OutcomeUnknown()

    # Its concluding write now matches nothing. On the SQLAlchemy store, whose read
    # passes the lock, that write still meets it; the sqlite3 store's read already
    # takes the lock.
    handler.begin_writing()
    with pytest.raises(StoreUnavailable, match="locked"):
        replay.admit(request)
    handler.commit()

    assert replay.admit(request) == OutcomeUnknown()
