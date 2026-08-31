from __future__ import annotations

import asyncio

import pytest
from compute_provisioning import ComputeProvisioningBackgroundTask

from compute_provisioning_service import worker


@pytest.mark.asyncio
async def test_worker_runs_background_tasks_and_cancels_them_cleanly(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def background_loop():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(worker.app_runtime, "startup_steps", lambda: ())
    monkeypatch.setattr(worker.app_runtime, "shutdown_steps", lambda: ())
    monkeypatch.setattr(
        worker.app_runtime,
        "background_tasks",
        lambda: (
            ComputeProvisioningBackgroundTask(
                "test-loop",
                background_loop,
                "test loop started",
            ),
        ),
    )

    stop = asyncio.Event()
    running = asyncio.create_task(worker.run_worker(stop))
    await asyncio.wait_for(started.wait(), timeout=1)
    stop.set()
    await asyncio.wait_for(running, timeout=1)

    assert cancelled.is_set()


def test_runtime_imports_pools_before_seeding_inventory():
    names = [step.name for step in worker.app_runtime.startup_steps()]
    assert names.index("import-pool-definitions") < names.index("seed-inventory")
