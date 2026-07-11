import asyncio

import pytest

from compute_provisioning.lifecycle import (
    cancel_background_tasks,
    create_background_task,
)


@pytest.mark.asyncio
async def test_create_background_task_sets_name():
    async def run():
        return "done"

    task = create_background_task(run(), name="example-task")

    assert task.get_name() == "example-task"
    assert await task == "done"


@pytest.mark.asyncio
async def test_cancel_background_tasks_waits_for_cancellation():
    cancelled = asyncio.Event()

    async def run_forever():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = create_background_task(run_forever(), name="forever")
    await asyncio.sleep(0)

    await cancel_background_tasks(task)

    assert task.cancelled()
    assert cancelled.is_set()
