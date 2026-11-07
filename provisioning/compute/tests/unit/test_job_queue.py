"""The job queue's idle signal: processing has ended, not just job status."""

from __future__ import annotations

import asyncio

import pytest

from compute_provisioning.jobs.queue import AsyncJobQueue


@pytest.mark.asyncio
async def test_idle_waits_for_every_dispatched_job_to_finish_processing() -> None:
    queue = AsyncJobQueue(max_concurrent=2)
    release = asyncio.Event()
    started: list[str] = []
    both_started = asyncio.Event()

    async def handler(job_id: str) -> None:
        started.append(job_id)
        if len(started) == 2:
            both_started.set()
        await release.wait()

    dispatcher = asyncio.create_task(queue.start(handler))
    try:
        await queue.enqueue("a")
        await queue.enqueue("b")
        await asyncio.wait_for(both_started.wait(), timeout=1.0)

        # Both handlers are blocked on ``release``, so idle cannot complete
        # until it is set.
        idle = asyncio.create_task(queue.wait_until_idle())
        done, _ = await asyncio.wait({idle}, timeout=0)
        assert not done

        release.set()
        await asyncio.wait_for(idle, timeout=1.0)
    finally:
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)


@pytest.mark.asyncio
async def test_an_idle_queue_returns_at_once() -> None:
    await asyncio.wait_for(AsyncJobQueue(max_concurrent=1).wait_until_idle(), timeout=1.0)
