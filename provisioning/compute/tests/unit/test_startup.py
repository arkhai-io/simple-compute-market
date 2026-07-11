from __future__ import annotations

import asyncio

import pytest

from compute_provisioning.startup import (
    ComputeProvisioningBackgroundTask,
    ComputeProvisioningShutdownStep,
    ComputeProvisioningStartupStep,
    start_compute_provisioning_runtime,
    stop_compute_provisioning_runtime,
)


@pytest.mark.asyncio
async def test_start_compute_provisioning_runtime_runs_steps_before_background_tasks():
    events: list[str] = []

    async def background():
        events.append("background-started")
        await asyncio.Event().wait()

    runtime = await start_compute_provisioning_runtime(
        startup_steps=(
            ComputeProvisioningStartupStep("first", lambda: events.append("first")),
            ComputeProvisioningStartupStep("second", lambda: events.append("second")),
        ),
        background_tasks=(
            ComputeProvisioningBackgroundTask("worker", background),
        ),
    )
    await asyncio.sleep(0)

    assert events == ["first", "second", "background-started"]

    await stop_compute_provisioning_runtime(runtime)


@pytest.mark.asyncio
async def test_start_compute_provisioning_runtime_resolves_background_task_factory_after_steps():
    events: list[str] = []
    resolved: dict[str, str] = {}

    async def background():
        events.append(resolved["service"])

    await start_compute_provisioning_runtime(
        startup_steps=(
            ComputeProvisioningStartupStep(
                "resolve-service",
                lambda: resolved.__setitem__("service", "ready"),
            ),
        ),
        background_tasks=lambda: (ComputeProvisioningBackgroundTask("worker", background),),
    )
    await asyncio.sleep(0)

    assert events == ["ready"]


@pytest.mark.asyncio
async def test_start_compute_provisioning_runtime_fails_fast_by_default():
    events: list[str] = []

    def fail():
        events.append("fail")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await start_compute_provisioning_runtime(
            startup_steps=(
                ComputeProvisioningStartupStep("fail", fail),
                ComputeProvisioningStartupStep("never", lambda: events.append("never")),
            )
        )

    assert events == ["fail"]


@pytest.mark.asyncio
async def test_start_compute_provisioning_runtime_can_continue_after_noncritical_error():
    events: list[str] = []

    def fail():
        events.append("fail")
        raise RuntimeError("boom")

    await start_compute_provisioning_runtime(
        startup_steps=(
            ComputeProvisioningStartupStep("fail", fail, continue_on_error=True),
            ComputeProvisioningStartupStep("next", lambda: events.append("next")),
        )
    )

    assert events == ["fail", "next"]


@pytest.mark.asyncio
async def test_stop_compute_provisioning_runtime_cancels_tasks_before_shutdown_steps():
    events: list[str] = []

    async def background():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("cancelled")
            raise

    runtime = await start_compute_provisioning_runtime(
        background_tasks=(ComputeProvisioningBackgroundTask("worker", background),)
    )
    await asyncio.sleep(0)

    await stop_compute_provisioning_runtime(
        runtime,
        shutdown_steps=(
            ComputeProvisioningShutdownStep("shutdown", lambda: events.append("shutdown")),
        ),
    )

    assert events == ["cancelled", "shutdown"]
