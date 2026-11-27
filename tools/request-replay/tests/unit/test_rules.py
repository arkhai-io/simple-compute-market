"""The guard's rules against the in-memory store double (`tests/rules.py`), and the
guard's own check of the row a store's concluding write answers."""

from dataclasses import replace

from request_replay import Dispatch, Expired, Resolution, Row

from tests.rules import *  # noqa: F401,F403
from tests.support import OUTCOME, POLICY, START, ManualClock, MemoryStore, entry, guard


class ConcludingWith:
    """A store whose concluding write answers ``row``, as one ignoring the request's
    identity would answer another request's row under the key."""

    def __init__(self, store: MemoryStore, row: Row) -> None:
        self._store = store
        self._row = row

    def __getattr__(self, name: str) -> object:
        return getattr(self._store, name)

    def conclude(self, entry: object, *, now: int) -> Row:
        return self._row


def test_the_guard_answers_expired_when_the_concluding_write_answers_another_request() -> None:
    store, clock = MemoryStore(), ManualClock()
    first = guard(store, clock).admit(entry(Resolution.RECORDED))
    assert isinstance(first, Dispatch)
    clock.advance(POLICY.lease_seconds)
    own = store.get("scheme:caller-1", "request-1", now=clock())
    other = replace(own, request_hash="hash-b", origin=START + 1, lease_until=None, outcome=OUTCOME)

    assert guard(ConcludingWith(store, other), clock).admit(entry(Resolution.RECORDED)) == Expired()
