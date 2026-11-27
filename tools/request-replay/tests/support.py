"""Test doubles: a clock, an in-memory store, store adapters, and entry builders.

The clock is moved by the test; the adapters refuse a store step or run another
party's step inside it.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import replace

from request_replay import Entry, Outcome, Policy, RequestReplay, Resolution, Row

START = 1_800_000_000
POLICY = Policy(skew_seconds=300, retention_seconds=86_400, lease_seconds=30)


class ManualClock:
    """The time source's instant, set by the test."""

    def __init__(self, now: int = START) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


def owners() -> itertools.count[int]:
    return itertools.count(1)


def guard(store: object, clock: ManualClock, policy: Policy = POLICY) -> RequestReplay:
    counter = owners()
    return RequestReplay(store, policy, clock=clock, new_owner=lambda: f"owner-{next(counter)}")  # type: ignore[arg-type]


def entry(
    resolution: Resolution,
    *,
    origin: int = START,
    request_id: str = "request-1",
    request_hash: str = "hash-a",
    principal: str = "scheme:caller-1",
) -> Entry:
    return Entry(
        principal=principal,
        request_id=request_id,
        request_hash=request_hash,
        resolution=resolution,
        origin=origin,
    )


OUTCOME = Outcome(
    status=201,
    headers=(("content-type", "application/json"), ("x-trace", "a")),
    body=b'{"created":true}',
)


class MemoryStore:
    """The store contract over a dictionary, for the guard's unit tests.

    A test double only: a process's memory forgets every reservation when it
    restarts, which would accept a replay.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], Row] = {}

    def claim(self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str) -> Row | None:
        key = (entry.principal, entry.request_id)
        existing = self.rows.get(key)
        if existing is not None and existing.expires_at > now:
            return existing
        self.rows[key] = Row(
            principal=entry.principal,
            request_id=entry.request_id,
            request_hash=entry.request_hash,
            resolution=entry.resolution,
            origin=entry.origin,
            expires_at=expires_at,
            lease_until=lease_until,
            lease_owner=owner,
            outcome=None,
        )
        return None

    def reclaim(self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str) -> bool:
        key = (entry.principal, entry.request_id)
        row = self.rows.get(key)
        if (
            row is None
            or row.request_hash != entry.request_hash
            or row.resolution is not Resolution.RERUN
            or row.outcome is not None
            or row.expires_at <= now
            or row.lease_held(now)
        ):
            return False
        self.rows[key] = replace(
            row, lease_until=lease_until, lease_owner=owner, expires_at=max(row.expires_at, expires_at)
        )
        return True

    def renew(self, principal: str, request_id: str, owner: str, *, now: int, lease_until: int) -> bool:
        row = self.rows.get((principal, request_id))
        if row is None or row.lease_owner != owner or row.outcome is not None or not row.lease_held(now):
            return False
        self.rows[(principal, request_id)] = replace(
            row, lease_until=lease_until, expires_at=max(row.expires_at, lease_until)
        )
        return True

    def conclude(self, entry: Entry, *, now: int) -> Row | None:
        principal, request_id = entry.principal, entry.request_id
        row = self.rows.get((principal, request_id))
        if (
            row is None
            or row.expires_at <= now
            or (row.request_hash, row.origin) != (entry.request_hash, entry.origin)
        ):
            return None
        if (
            row.resolution is Resolution.RECORDED
            and row.outcome is None
            and row.lease_until is not None
            and row.lease_until <= now
        ):
            row = replace(row, lease_until=None)
            self.rows[(principal, request_id)] = row
        return row

    def record(self, principal: str, request_id: str, owner: str, outcome: Outcome) -> bool:
        row = self.rows.get((principal, request_id))
        if row is None or row.lease_owner != owner:
            return False
        self.rows[(principal, request_id)] = replace(row, outcome=outcome, lease_until=None, lease_owner=None)
        return True

    def release(self, principal: str, request_id: str, owner: str) -> bool:
        row = self.rows.get((principal, request_id))
        if row is None or row.lease_owner != owner:
            return False
        self.rows[(principal, request_id)] = replace(row, lease_until=None, lease_owner=None)
        return True

    def get(self, principal: str, request_id: str, *, now: int) -> Row | None:
        row = self.rows.get((principal, request_id))
        return row if row is not None and row.expires_at > now else None

    def sweep_batch(self, *, now: int, limit: int) -> int:
        expired = sorted((row.expires_at, key) for key, row in self.rows.items() if row.expires_at <= now)
        for _, key in expired[:limit]:
            del self.rows[key]
        return min(len(expired), limit)


class Refusing:
    """A store whose named steps fail, as a store refusing or timing out does."""

    def __init__(self, store: object, *steps: str) -> None:
        self._store = store
        self._steps = steps

    def __getattr__(self, name: str) -> object:
        if name in self._steps:

            def refused(*args: object, **kwargs: object) -> object:
                raise ConnectionError("database is locked")

            return refused
        return getattr(self._store, name)


class RecordingFirst:
    """A store whose concluding step lets the attempt record its outcome first, as
    when the handler returns between the retry's read and its write."""

    def __init__(self, store: object, record: Callable[[], None]) -> None:
        self._store = store
        self._record = record
        self.recorded = False

    def __getattr__(self, name: str) -> object:
        target = getattr(self._store, name)
        if name != "conclude":
            return target

        def recorded_first(*args: object, **kwargs: object) -> object:
            self._record()
            self.recorded = True
            return target(*args, **kwargs)

        return recorded_first


class TakenFirst:
    """A store whose concluding step lets another party take the key first, as when
    the retry's row expires and another request claims its key between the retry's
    read and its concluding write."""

    def __init__(self, store: object, take: Callable[[], None]) -> None:
        self._store = store
        self._take = take

    def __getattr__(self, name: str) -> object:
        target = getattr(self._store, name)
        if name != "conclude":
            return target

        def taken_first(*args: object, **kwargs: object) -> object:
            self._take()
            return target(*args, **kwargs)

        return taken_first
