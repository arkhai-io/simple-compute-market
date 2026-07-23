"""Bounded-concurrency async job queue.

``AsyncJobQueue`` owns the ``asyncio.Queue``, the ``asyncio.Semaphore``, and
the running-task bookkeeping that previously lived inside ``AnsibleJobService``.
It knows nothing about Ansible, the database, or job semantics — it is a pure
async dispatch primitive.

Separation of concerns:
  - ``AsyncJobQueue``   — queue lifecycle, concurrency limiting, task dispatch
  - ``AnsibleJobService`` — DB state, retry logic, job handler implementation
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Optional

logger = logging.getLogger(__name__)


class AsyncJobQueue:
    """Bounded-concurrency async queue for string job IDs.

    Usage::

        queue = AsyncJobQueue(max_concurrent=5)
        await queue.enqueue("job-id-123")
        await queue.start(handler)   # long-lived; runs until cancelled

    The ``handler`` coroutine receives a single ``job_id: str`` argument and is
    responsible for all processing logic.  ``AsyncJobQueue`` ensures at most
    ``max_concurrent`` handlers run simultaneously.

    ``on_job_started`` is an optional test-seam callback invoked (synchronously,
    inside the dispatch loop) just before the handler task is created.  It is
    ``None`` in production paths and therefore zero-cost.
    """

    def __init__(
        self,
        max_concurrent: int,
        on_job_started: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._on_job_started = on_job_started

        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._running_tasks: set[asyncio.Task] = set()
        self._dispatch_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def enqueue(self, job_id: str) -> None:
        """Place *job_id* on the queue.  Returns immediately."""
        await self._queue.put(job_id)

    def is_alive(self) -> bool:
        """Return True if the dispatch loop task is running."""
        return (
            self._dispatch_task is not None
            and not self._dispatch_task.done()
        )

    async def start(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Dequeue job IDs and dispatch them concurrently to *handler*.

        Intended to run as a long-lived ``asyncio.Task`` started in the
        FastAPI lifespan.  Exits cleanly on ``asyncio.CancelledError``.
        """
        self._dispatch_task = asyncio.current_task()

        logger.info(
            "AsyncJobQueue started (max_concurrent=%d)", self._max_concurrent
        )

        while True:
            try:
                try:
                    job_id = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._reap_done_tasks()
                    continue

                if self._on_job_started is not None:
                    self._on_job_started(job_id)

                task = asyncio.create_task(
                    self._dispatch(job_id, handler),
                    name=f"job-{job_id[:8]}",
                )
                self._running_tasks.add(task)
                self._reap_done_tasks()

                logger.debug(
                    "AsyncJobQueue: %d active jobs", len(self._running_tasks)
                )

            except asyncio.CancelledError:
                logger.info("AsyncJobQueue dispatch loop cancelled")
                break
            except Exception as exc:
                logger.exception("AsyncJobQueue dispatch loop error: %s", exc)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _dispatch(
        self, job_id: str, handler: Callable[[str], Awaitable[None]]
    ) -> None:
        async with self._semaphore:
            try:
                await handler(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "AsyncJobQueue: unhandled exception in handler for job %s: %s",
                    job_id,
                    exc,
                )

    def _reap_done_tasks(self) -> None:
        done = {t for t in self._running_tasks if t.done()}
        self._running_tasks.difference_update(done)
