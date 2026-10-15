"""In-memory storefront caches for independently versioned site projections."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Generic, Mapping, Protocol, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ProjectionIdentity:
    revision: int
    digest: str


class ProjectionState(str, Enum):
    not_loaded = "not_loaded"
    loaded = "loaded"
    stale = "stale"
    unavailable = "unavailable"
    invalid = "invalid"


class ProjectionClient(Protocol, Generic[T]):
    async def version(self) -> ProjectionIdentity: ...
    async def snapshot(self) -> tuple[ProjectionIdentity, T]: ...


@dataclass(frozen=True)
class ProjectionCacheView(Generic[T]):
    """One projection family's current cached state.

    fetched_at:
        When this generation was last *confirmed* current, not only when
        its payload was last transferred. A `poll_once()` that finds the
        remote identity unchanged advances this without re-fetching the
        snapshot body -- deliberately: an operator reading this value
        wants to know "how stale could this be," and a confirmed-unchanged
        poll answers that exactly as well as a full re-fetch would, at far
        lower cost. `None` until the first successful load or confirmation.
    """

    identity: ProjectionIdentity | None
    value: T | None
    state: ProjectionState
    last_error: str | None
    fetched_at: datetime | None


class ProjectionCache(Generic[T]):
    """Refresh one projection family without exposing partial generations.

    Every operation -- a version poll, a forced snapshot, a drift check -- runs
    under one lock, its version check included, so operations on the family
    never overlap. A poll that arrives while another operation runs does not
    queue: it waits for that operation and returns its result rather than
    polling again, because a confirmation already in progress answers it. A
    forced refresh queues behind the running operation and then fetches,
    because its caller asked for a snapshot taken after its own change. Either
    way, a failed operation never replaces a confirmation that completed after
    it began.
    """

    def __init__(
        self,
        client: ProjectionClient[T],
        *,
        validate: Callable[[T], None] | None = None,
    ) -> None:
        self._client = client
        self._validate = validate or (lambda _: None)
        self._identity: ProjectionIdentity | None = None
        self._value: T | None = None
        self._state = ProjectionState.not_loaded
        self._last_error: str | None = None
        self._fetched_at: datetime | None = None
        self._lock = asyncio.Lock()
        self._running: asyncio.Future[ProjectionCacheView[T]] | None = None

    def view(self) -> ProjectionCacheView[T]:
        return ProjectionCacheView(
            self._identity, self._value, self._state, self._last_error, self._fetched_at,
        )

    async def load(self) -> ProjectionCacheView[T]:
        return await self.refresh(force=True)

    async def poll_once(self) -> ProjectionCacheView[T]:
        running = self._running
        if running is not None:
            try:
                return await asyncio.shield(running)
            except asyncio.CancelledError:
                # Only when the joined operation was cancelled and this caller
                # was not does the caller poll for itself, rather than report a
                # result nobody produced.
                current = asyncio.current_task()
                if not running.cancelled() or (
                    current is not None and current.cancelling()
                ):
                    raise
        return await self._exclusive(self._poll_locked)

    async def refresh(self, *, force: bool = False) -> ProjectionCacheView[T]:
        if not force:
            return await self.poll_once()
        return await self._exclusive(self._refresh_locked)

    async def refresh_after_topology_error(
        self, observed_identity: ProjectionIdentity | None
    ) -> bool:
        """Coalesce one reactive version check and report whether drift existed."""
        before = observed_identity or self._identity
        view = await self.poll_once()
        return view.identity is not None and before is not None and view.identity != before

    async def _exclusive(
        self, operation: Callable[[], Awaitable[ProjectionCacheView[T]]]
    ) -> ProjectionCacheView[T]:
        async with self._lock:
            running: asyncio.Future[ProjectionCacheView[T]] = (
                asyncio.get_running_loop().create_future()
            )
            self._running = running
            try:
                view = await operation()
                running.set_result(view)
                return view
            finally:
                self._running = None
                if not running.done():
                    running.cancel()

    async def _poll_locked(self) -> ProjectionCacheView[T]:
        try:
            remote = await self._client.version()
        except Exception as exc:
            self._last_error = str(exc)
            self._state = ProjectionState.stale if self._value is not None else ProjectionState.unavailable
            return self.view()
        if self._identity is not None and remote == self._identity:
            self._last_error = None
            self._state = ProjectionState.loaded
            self._fetched_at = datetime.now(timezone.utc)
            return self.view()
        return await self._refresh_locked()

    async def _refresh_locked(self) -> ProjectionCacheView[T]:
        try:
            identity, value = await self._client.snapshot()
            self._validate(value)
        except Exception as exc:
            self._last_error = str(exc)
            self._state = ProjectionState.stale if self._value is not None else ProjectionState.invalid
            return self.view()
        self._identity = identity
        self._value = value
        self._last_error = None
        self._state = ProjectionState.loaded
        self._fetched_at = datetime.now(timezone.utc)
        return self.view()
