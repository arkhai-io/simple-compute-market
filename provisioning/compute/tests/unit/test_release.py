from __future__ import annotations

from typing import Any

import pytest

from compute_provisioning.release import ExecutorReleaseDispatcher


class RecordingReleaseExecutor:
    def __init__(self, job_id: str | None) -> None:
        self.job_id = job_id
        self.allocations: list[dict[str, Any]] = []

    async def submit_release(self, allocation: dict[str, Any]) -> str | None:
        self.allocations.append(allocation)
        return self.job_id


@pytest.mark.asyncio
async def test_dispatcher_routes_by_executor_kind():
    vm_executor = RecordingReleaseExecutor("vm-job")
    bare_metal_executor = RecordingReleaseExecutor("bare-metal-job")
    dispatcher = ExecutorReleaseDispatcher({
        "vm": vm_executor,
        "bare_metal": bare_metal_executor,
    })

    result = await dispatcher.submit_release({"executor_kind": "bare_metal"})

    assert result == "bare-metal-job"
    assert vm_executor.allocations == []
    assert bare_metal_executor.allocations == [{"executor_kind": "bare_metal"}]


@pytest.mark.asyncio
async def test_dispatcher_uses_injected_default_executor_kind():
    vm_executor = RecordingReleaseExecutor("vm-job")
    dispatcher = ExecutorReleaseDispatcher(
        {"vm": vm_executor},
        default_executor_kind="vm",
    )

    result = await dispatcher.submit_release({"allocation_id": "alloc-1"})

    assert result == "vm-job"
    assert vm_executor.allocations == [{"allocation_id": "alloc-1"}]


@pytest.mark.asyncio
async def test_dispatcher_returns_none_for_unknown_executor_kind():
    dispatcher = ExecutorReleaseDispatcher({"vm": RecordingReleaseExecutor("vm-job")})

    result = await dispatcher.submit_release({"executor_kind": "bare_metal"})

    assert result is None
