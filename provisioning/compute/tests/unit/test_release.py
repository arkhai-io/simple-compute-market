from __future__ import annotations

from typing import Any

import pytest

from compute_provisioning.release import ExecutorReleaseDispatcher, ReleaseJobDispatcher


class RecordingReleaseExecutor:
    def __init__(self, job_id: str | None) -> None:
        self.job_id = job_id
        self.reservations: list[dict[str, Any]] = []

    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        self.reservations.append(reservation)
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
    assert vm_executor.reservations == []
    assert bare_metal_executor.reservations == [{"executor_kind": "bare_metal"}]


@pytest.mark.asyncio
async def test_dispatcher_does_not_default_missing_executor_kind():
    vm_executor = RecordingReleaseExecutor("vm-job")
    dispatcher = ExecutorReleaseDispatcher({"vm": vm_executor})

    result = await dispatcher.submit_release({"capacity_reservation_id": "alloc-1"})

    assert result is None
    assert vm_executor.reservations == []


@pytest.mark.asyncio
async def test_dispatcher_returns_none_for_unknown_executor_kind():
    dispatcher = ExecutorReleaseDispatcher({"vm": RecordingReleaseExecutor("vm-job")})

    result = await dispatcher.submit_release({"executor_kind": "bare_metal"})

    assert result is None


class RecordingReleaseJobPort:
    def __init__(self, job: Any) -> None:
        self.job = job
        self.job_ids: list[str] = []

    def get_job(self, job_id: str) -> Any:
        self.job_ids.append(job_id)
        return self.job


def test_release_job_dispatcher_routes_by_executor_kind():
    vm_job = object()
    bare_metal_job = object()
    vm_port = RecordingReleaseJobPort(vm_job)
    bare_metal_port = RecordingReleaseJobPort(bare_metal_job)
    dispatcher = ReleaseJobDispatcher({
        "vm": vm_port,
        "bare_metal": bare_metal_port,
    })

    result = dispatcher.get_job("job-1", executor_kind="bare_metal")

    assert result is bare_metal_job
    assert vm_port.job_ids == []
    assert bare_metal_port.job_ids == ["job-1"]


def test_release_job_dispatcher_does_not_default_missing_executor_kind():
    vm_port = RecordingReleaseJobPort(object())
    dispatcher = ReleaseJobDispatcher({"vm": vm_port})

    with pytest.raises(LookupError):
        dispatcher.get_job("job-1")
    assert vm_port.job_ids == []


def test_release_job_dispatcher_raises_lookup_error_for_unregistered_executor_kind():
    dispatcher = ReleaseJobDispatcher({"vm": RecordingReleaseJobPort(object())})

    with pytest.raises(LookupError):
        dispatcher.get_job("job-1", executor_kind="bare_metal")


def test_release_job_dispatcher_raises_lookup_error_with_no_kind_and_no_default():
    dispatcher = ReleaseJobDispatcher({"vm": RecordingReleaseJobPort(object())})

    with pytest.raises(LookupError):
        dispatcher.get_job("job-1")
