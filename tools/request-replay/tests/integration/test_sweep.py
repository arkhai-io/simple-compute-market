from __future__ import annotations

from collections.abc import Callable

from request_replay import Dispatch, InProgress, Resolution

from tests.support import POLICY, START, ManualClock, entry, guard

SKEW = POLICY.skew_seconds


class CountingStore:
    """A store recording the size of every sweep batch it is asked for."""

    def __init__(self, store: object) -> None:
        self._store = store
        self.batches: list[int] = []

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def sweep_batch(self, *, now: int, limit: int) -> int:
        deleted = self._store.sweep_batch(now=now, limit=limit)  # type: ignore[attr-defined]
        self.batches.append(deleted)
        return deleted


def _expired_backlog(store: object, clock: ManualClock, count: int) -> None:
    replay = guard(store, clock)
    for index in range(count):
        first = replay.admit(entry(Resolution.RERUN, request_id=f"r-{index}"))
        assert isinstance(first, Dispatch)
    clock.advance(2 * SKEW)


def test_a_backlog_is_swept_in_bounded_batches(store) -> None:
    clock = ManualClock()
    _expired_backlog(store, clock, 250)
    counting = CountingStore(store)

    assert guard(counting, clock).sweep(batch_size=100) == 250

    assert counting.batches == [100, 100, 50]
    assert guard(store, clock).sweep() == 0


def test_a_running_old_origin_rerun_attempt_keeps_its_row_through_the_sweep(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    old = entry(Resolution.RERUN, origin=START - 6 * 3600)
    assert isinstance(replay.admit(old), Dispatch)

    clock.advance(POLICY.lease_seconds - 1)
    assert replay.sweep() == 0

    assert replay.admit(old) == InProgress()


def test_two_sweepers_over_one_database_delete_each_row_once(make_store: Callable[[], object]) -> None:
    clock = ManualClock()
    _expired_backlog(make_store(), clock, 120)
    first, second = make_store(), make_store()

    deleted = []
    while True:
        batch = [
            first.sweep_batch(now=clock(), limit=25),  # type: ignore[attr-defined]
            second.sweep_batch(now=clock(), limit=25),  # type: ignore[attr-defined]
        ]
        deleted.extend(batch)
        if batch == [0, 0]:
            break

    assert sum(deleted) == 120
    assert guard(first, clock).sweep() == 0
