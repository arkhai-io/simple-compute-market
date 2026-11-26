"""Two guards over one database, each through its own connections.

A competing step is run at a fixed point inside another's, through a test-only
adapter on the store's narrow interface, so the interleaving is the test's and
never the scheduler's.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from request_replay import Admission, Dispatch, InProgress, Resolution, SqliteReplayStore
from request_replay.sqlalchemy_store import SqlAlchemyReplayStore

from tests.support import POLICY, ManualClock, entry, guard


class CompetingFirst:
    """A store whose named step lets a competitor admit the same request first."""

    def __init__(self, store: object, step: str, compete: Callable[[], Admission]) -> None:
        self._store = store
        self._step = step
        self._compete = compete
        self.competitor: Admission | None = None

    def __getattr__(self, name: str) -> object:
        target = getattr(self._store, name)
        if name != self._step:
            return target

        def competed(*args: object, **kwargs: object) -> object:
            self.competitor = self._compete()
            return target(*args, **kwargs)

        return competed


def test_of_two_first_uses_racing_one_is_dispatched_and_the_other_in_progress(
    make_store: Callable[[], object],
) -> None:
    clock = ManualClock()
    request = entry(Resolution.RECORDED)
    rival = guard(make_store(), clock)
    racing = CompetingFirst(make_store(), "claim", lambda: rival.admit(request))

    assert guard(racing, clock).admit(request) == InProgress()
    assert isinstance(racing.competitor, Dispatch)


def test_of_two_retries_racing_for_an_ended_rerun_lease_one_reclaims_it(
    make_store: Callable[[], object],
) -> None:
    clock = ManualClock()
    request = entry(Resolution.RERUN)
    store = make_store()
    assert isinstance(guard(store, clock).admit(request), Dispatch)
    clock.advance(POLICY.lease_seconds)
    rival = guard(make_store(), clock)
    racing = CompetingFirst(make_store(), "reclaim", lambda: rival.admit(request))

    assert guard(racing, clock).admit(request) == InProgress()

    assert isinstance(racing.competitor, Dispatch) and racing.competitor.exact_retry is True
    row = store.get("scheme:caller-1", "request-1", now=clock())  # type: ignore[attr-defined]
    assert row.lease_owner == racing.competitor.attempt.owner


def test_a_sqlite_step_waits_for_the_write_lock_before_it_reads(database: Path) -> None:
    holder = sqlite3.connect(database, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    store = SqliteReplayStore(lambda: sqlite3.connect(database, timeout=0))
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            guard(store, ManualClock()).admit(entry(Resolution.RERUN))
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert isinstance(guard(store, ManualClock()).admit(entry(Resolution.RERUN)), Dispatch)


class VanishingConflicts(SqlAlchemyReplayStore):
    """A store whose first inserts meet a key conflict whose row is gone by the read,
    as when a sweep deletes it in between."""

    def __init__(self, *args: object, conflicts: int, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.conflicts = conflicts

    def _insert(self, entry: object, **kwargs: object) -> None:  # type: ignore[override]
        if self.conflicts:
            self.conflicts -= 1
            raise IntegrityError("INSERT", {}, Exception("key held by a row since deleted"))
        super()._insert(entry, **kwargs)  # type: ignore[arg-type]


def test_a_claim_whose_conflicting_row_vanished_claims_again(database: Path) -> None:
    engine = create_engine(f"sqlite:///{database}")
    try:
        store = VanishingConflicts(engine, conflicts=1)

        assert isinstance(guard(store, ManualClock()).admit(entry(Resolution.RERUN)), Dispatch)
        with pytest.raises(RuntimeError, match="kept changing"):
            guard(VanishingConflicts(engine, conflicts=3), ManualClock()).admit(
                entry(Resolution.RERUN, request_id="request-2")
            )
    finally:
        engine.dispose()
