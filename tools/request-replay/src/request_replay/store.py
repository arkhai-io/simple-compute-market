"""The store contract: one row per reserved request, and the atomic steps on it.

A row is keyed by an opaque principal and request ID. It holds the request's hash,
its resolution and origin, the instant it expires, the lease of the attempt
running it, and, for a recorded request, the response that attempt returned. A
row whose expiry has passed is absent to every step but the sweep: it answers
nothing and refuses nothing, and a reservation under its key replaces it.

Each method is one transaction. Instants are integer seconds on the caller's time
source; the store reads no clock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from request_replay.policy import Resolution


@dataclass(frozen=True)
class Outcome:
    """A response as recorded: its status, its headers in order, and its body."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int):
            raise ValueError("status must be an integer")
        if not 100 <= self.status <= 599:
            raise ValueError("status must be an HTTP status code")

    def headers_json(self) -> str:
        """The headers as a store writes them."""

        return json.dumps([list(pair) for pair in self.headers], separators=(",", ":"))

    @staticmethod
    def headers_from_json(text: str) -> tuple[tuple[str, str], ...]:
        return tuple((str(name), str(value)) for name, value in json.loads(text))


@dataclass(frozen=True)
class Entry:
    """What a request asks to reserve: its key, hash, resolution and origin."""

    principal: str
    request_id: str
    request_hash: str
    resolution: Resolution
    origin: int


@dataclass(frozen=True)
class Row:
    """A live row, as a store read it."""

    principal: str
    request_id: str
    request_hash: str
    resolution: Resolution
    origin: int
    expires_at: int
    lease_until: int | None
    lease_owner: str | None
    outcome: Outcome | None

    def lease_held(self, now: int) -> bool:
        return self.lease_until is not None and self.lease_until > now


class ReplayStore(Protocol):
    """The atomic steps a replay guard takes on its rows."""

    def claim(
        self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str
    ) -> Row | None:
        """Reserve ``entry``'s key with a lease held by ``owner``.

        A row under the key whose expiry is at or before ``now`` is replaced.
        Answers ``None`` once reserved, or the live row already holding the key,
        unchanged.
        """
        ...

    def reclaim(
        self, entry: Entry, *, now: int, expires_at: int, lease_until: int, owner: str
    ) -> bool:
        """Take the lease of a live, unrecorded re-run row with ``entry``'s hash.

        Succeeds only where no lease is held at ``now``, so of two retries one
        reclaims. Raises the row's expiry to ``expires_at`` where that is later.
        """
        ...

    def renew(self, principal: str, request_id: str, owner: str, *, now: int, lease_until: int) -> bool:
        """Extend the lease ``owner`` still holds at ``now`` to ``lease_until``.

        Raises the row's expiry with it. Does nothing once the row is recorded,
        released, or reclaimed by another owner, or once its lease has ended.
        """
        ...

    def record(self, principal: str, request_id: str, owner: str, outcome: Outcome) -> bool:
        """Record ``owner``'s response and clear its lease."""
        ...

    def release(self, principal: str, request_id: str, owner: str) -> bool:
        """Clear the lease ``owner`` holds, recording nothing."""
        ...

    def get(self, principal: str, request_id: str, *, now: int) -> Row | None:
        """The live row under the key at ``now``, if any."""
        ...

    def sweep_batch(self, *, now: int, limit: int) -> int:
        """Delete at most ``limit`` rows expired at ``now``; answer how many."""
        ...


COLUMNS = (
    "principal",
    "request_id",
    "request_hash",
    "resolution",
    "origin",
    "expires_at",
    "lease_until",
    "lease_owner",
    "outcome_status",
    "outcome_headers",
    "outcome_body",
)
"""The table's columns, in the order a store reads a row."""


def row_from_columns(values: tuple[Any, ...] | Any) -> Row:
    """A row from its :data:`COLUMNS` values, as either store reads them."""

    (
        principal,
        request_id,
        request_hash,
        resolution,
        origin,
        expires_at,
        lease_until,
        lease_owner,
        outcome_status,
        outcome_headers,
        outcome_body,
    ) = values
    outcome = None
    if outcome_status is not None:
        outcome = Outcome(
            status=int(outcome_status),
            headers=Outcome.headers_from_json(outcome_headers or "[]"),
            body=bytes(outcome_body or b""),
        )
    return Row(
        principal=str(principal),
        request_id=str(request_id),
        request_hash=str(request_hash),
        resolution=Resolution(resolution),
        origin=int(origin),
        expires_at=int(expires_at),
        lease_until=None if lease_until is None else int(lease_until),
        lease_owner=None if lease_owner is None else str(lease_owner),
        outcome=outcome,
    )
