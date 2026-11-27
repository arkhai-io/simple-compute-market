"""Every failing store step surfaces as one failure, chained to what the store raised.

Unit tests against the in-memory double behind an adapter that fails the named
steps: the adapter raises before any store is reached, so a real store adds nothing.
"""

from __future__ import annotations

import pytest

from request_replay import Dispatch, Resolution, StoreUnavailable

from tests.support import OUTCOME, POLICY, START, ManualClock, MemoryStore, Refusing, entry, guard

RERUN = Resolution.RERUN
RECORDED = Resolution.RECORDED
LEASE = POLICY.lease_seconds


def test_a_store_refusing_the_concluding_write_surfaces_store_unavailable() -> None:
    store, clock = MemoryStore(), ManualClock()
    first = guard(store, clock).admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    clock.advance(LEASE)

    with pytest.raises(StoreUnavailable, match="locked") as refused:
        guard(Refusing(store, "conclude"), clock).admit(entry(RECORDED))

    assert isinstance(refused.value.__cause__, ConnectionError)
    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert row is not None and not row.concluded
    assert (row.lease_until, row.lease_owner) == (START + LEASE, first.attempt.owner)


def test_a_store_refusing_any_other_step_surfaces_store_unavailable() -> None:
    store, clock = MemoryStore(), ManualClock()
    with pytest.raises(StoreUnavailable):
        guard(Refusing(store, "claim"), clock).admit(entry(RERUN))
    with pytest.raises(StoreUnavailable):
        guard(Refusing(store, "get"), clock).admit(entry(RECORDED, origin=START - POLICY.skew_seconds - 1))
    rerun = guard(store, clock).admit(entry(RERUN))
    recorded = guard(store, clock).admit(entry(RECORDED, request_id="request-2"))
    assert isinstance(rerun, Dispatch) and isinstance(recorded, Dispatch)
    for step, act in (
        ("release", lambda replay: replay.complete(rerun.attempt, OUTCOME)),
        ("record", lambda replay: replay.complete(recorded.attempt, OUTCOME)),
        ("renew", lambda replay: replay.renew(rerun.attempt)),
        ("sweep_batch", lambda replay: replay.sweep()),
    ):
        with pytest.raises(StoreUnavailable) as refused:
            act(guard(Refusing(store, step), clock))
        assert isinstance(refused.value.__cause__, ConnectionError)
    clock.advance(LEASE)
    with pytest.raises(StoreUnavailable):
        guard(Refusing(store, "reclaim"), clock).admit(entry(RERUN))
