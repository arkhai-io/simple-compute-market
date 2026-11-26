"""The replay guard: one admission per request, resolved against its row.

A request arrives as an :class:`Entry` the caller has already authenticated: its
principal, its request ID, a hash of everything it asks, its resolution, and its
origin -- the instant it was first signed, unchanged on every retry. The guard
answers what to do with it:

- :class:`Dispatch` -- run the handler, holding the attempt's lease;
  ``exact_retry`` says the request was seen before, on a re-run route;
- :class:`Answered` -- a recorded request's response, for an exact retry;
- :class:`InProgress` -- an attempt holds the request's lease;
- :class:`ChangedReuse` -- the key was reserved with a different hash;
- :class:`OutcomeUnknown` -- a recorded request's attempt ended without
  recording a response, so whether it applied is not known here;
- :class:`Expired` -- a recorded request past its retention, or whose origin
  is too old for a first use and whose row is gone.

Once its handler returns or raises, an attempt is completed: a recorded request's
response is recorded, a re-run request's lease released.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Union

from request_replay.policy import Policy, Resolution
from request_replay.store import Entry, Outcome, ReplayStore, Row

logger = logging.getLogger(__name__)

DEFAULT_SWEEP_BATCH = 500
"""Rows a sweep deletes per transaction, so a backlog never holds a write lock long."""


@dataclass(frozen=True)
class Attempt:
    """One dispatch of a request, holding its lease as ``owner``.

    ``lease_until`` is when the lease ends as admitted, before any renewal.
    """

    principal: str
    request_id: str
    resolution: Resolution
    owner: str
    lease_until: int


@dataclass(frozen=True)
class Dispatch:
    attempt: Attempt
    exact_retry: bool


@dataclass(frozen=True)
class Answered:
    outcome: Outcome


@dataclass(frozen=True)
class InProgress:
    pass


@dataclass(frozen=True)
class ChangedReuse:
    pass


@dataclass(frozen=True)
class OutcomeUnknown:
    pass


@dataclass(frozen=True)
class Expired:
    pass


Admission = Union[Dispatch, Answered, InProgress, ChangedReuse, OutcomeUnknown, Expired]


class RequestReplay:
    """Admits requests against a store under a policy and a time source.

    ``clock`` answers the time source's instant in whole seconds; every expiry
    and lease the guard writes is on it.
    """

    def __init__(
        self,
        store: ReplayStore,
        policy: Policy,
        *,
        clock: Callable[[], int],
        new_owner: Callable[[], str] = lambda: secrets.token_hex(16),
    ) -> None:
        self._store = store
        self._policy = policy
        self._clock = clock
        self._new_owner = new_owner

    @property
    def policy(self) -> Policy:
        return self._policy

    def now(self) -> int:
        """The time source's instant, on which every lease and expiry is written."""

        return self._clock()

    def admit(self, entry: Entry) -> Admission:
        now = self._clock()
        lease_until = now + self._policy.lease_seconds
        if entry.resolution is Resolution.RECORDED and not self._policy.admits_first_use(
            entry.origin, now
        ):
            # Only a row answers a recorded retry: with none it may already have
            # applied, and dispatching it again could apply it twice.
            row = self._store.get(entry.principal, entry.request_id, now=now)
            return Expired() if row is None else self._resolve(entry, row, now)
        owner = self._new_owner()
        held = self._store.claim(
            entry,
            now=now,
            expires_at=self._policy.expires_at(entry.resolution, entry.origin, lease_until),
            lease_until=lease_until,
            owner=owner,
        )
        if held is None:
            # A first use is signed now. A re-run request whose origin is older than
            # the skew is a retry whose row has gone, and its handler is told so.
            first_use = self._policy.admits_first_use(entry.origin, now)
            return Dispatch(self._attempt(entry, owner, lease_until), exact_retry=not first_use)
        return self._resolve(entry, held, now)

    def renew(self, attempt: Attempt) -> int | None:
        """Extend a running attempt's lease by a full period from now.

        Answers when the lease now ends, or ``None`` when the attempt does not
        hold it: its lease ended, or its outcome is recorded.
        """

        now = self._clock()
        lease_until = now + self._policy.lease_seconds
        held = self._store.renew(
            attempt.principal,
            attempt.request_id,
            attempt.owner,
            now=now,
            lease_until=lease_until,
        )
        return lease_until if held else None

    def complete(self, attempt: Attempt, outcome: Outcome) -> None:
        """End an attempt: record a recorded request's response, release a re-run one."""

        if attempt.resolution is Resolution.RECORDED:
            done = self._store.record(attempt.principal, attempt.request_id, attempt.owner, outcome)
        else:
            done = self._store.release(attempt.principal, attempt.request_id, attempt.owner)
        if not done:
            # The row left this attempt: swept after its lease ended, or reclaimed
            # by a re-run retry. A recorded retry since was told the outcome is
            # unknown, or will be told the response expired.
            logger.warning(
                "request %s of %s was not held by its attempt when it completed",
                attempt.request_id,
                attempt.principal,
            )

    def sweep(self, *, batch_size: int = DEFAULT_SWEEP_BATCH) -> int:
        """Delete every row expired now, ``batch_size`` per transaction."""

        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        now = self._clock()
        total = 0
        while True:
            deleted = self._store.sweep_batch(now=now, limit=batch_size)
            total += deleted
            if deleted < batch_size:
                return total

    def _resolve(self, entry: Entry, row: Row, now: int) -> Admission:
        if row.request_hash != entry.request_hash:
            return ChangedReuse()
        if row.resolution is Resolution.RECORDED:
            if self._policy.retention_passed(entry.origin, now):
                return Expired()
            if row.outcome is not None:
                return Answered(row.outcome)
            return InProgress() if row.lease_held(now) else OutcomeUnknown()
        if row.lease_held(now):
            return InProgress()
        owner = self._new_owner()
        lease_until = now + self._policy.lease_seconds
        reclaimed = self._store.reclaim(
            entry,
            now=now,
            expires_at=self._policy.expires_at(entry.resolution, entry.origin, lease_until),
            lease_until=lease_until,
            owner=owner,
        )
        # Another retry reclaimed the lease between the read and the update.
        return Dispatch(self._attempt(entry, owner, lease_until), exact_retry=True) if reclaimed else InProgress()

    @staticmethod
    def _attempt(entry: Entry, owner: str, lease_until: int) -> Attempt:
        return Attempt(
            principal=entry.principal,
            request_id=entry.request_id,
            resolution=entry.resolution,
            owner=owner,
            lease_until=lease_until,
        )
