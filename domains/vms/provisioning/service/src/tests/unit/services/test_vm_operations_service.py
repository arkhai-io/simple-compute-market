from unittest.mock import AsyncMock, MagicMock

import pytest

from models.jobs_model import JobSubmitResponse
from models.vm_request_model import CreateVmRequest, VmActionRequest
from services.vm_operations_service import VmOperationsService


@pytest.mark.asyncio
async def test_create_vm_submits_create_params_to_resolved_queue():
    job_queue = object()
    job_service = MagicMock()
    job_service.submit = AsyncMock(return_value=JobSubmitResponse(job_id="job-1", status="queued"))
    service = VmOperationsService(job_service=job_service, job_queue_provider=lambda: job_queue)

    body = CreateVmRequest(vm_target="vm-1", vm_ram=2048, vm_vcpus=2)
    response = await service.create_vm(host="kvm1", body=body)

    assert response.job_id == "job-1"
    params, queue = job_service.submit.await_args.args
    assert params.vm_host == "kvm1"
    assert params.vm_action == "create"
    assert params.vm_target == "vm-1"
    assert params.vm_ram == 2048
    assert queue is job_queue


@pytest.mark.asyncio
async def test_submit_action_builds_simple_vm_action_params():
    job_queue = object()
    job_service = MagicMock()
    job_service.submit = AsyncMock(return_value=JobSubmitResponse(job_id="job-2", status="queued"))
    service = VmOperationsService(job_service=job_service, job_queue_provider=lambda: job_queue)

    await service.submit_action(
        action="reboot",
        host="kvm1",
        vm_name="vm-1",
        body=VmActionRequest(max_retries=4),
    )

    params, queue = job_service.submit.await_args.args
    assert params.vm_host == "kvm1"
    assert params.vm_action == "reboot"
    assert params.vm_target == "vm-1"
    assert params.max_retries == 4
    assert queue is job_queue


@pytest.mark.asyncio
async def test_list_vms_builds_host_scoped_params_without_vm_target():
    job_service = MagicMock()
    job_service.submit = AsyncMock(return_value=JobSubmitResponse(job_id="job-3", status="queued"))
    service = VmOperationsService(job_service=job_service, job_queue_provider=lambda: object())

    await service.list_vms(host="kvm1", body=VmActionRequest())

    params, _ = job_service.submit.await_args.args
    assert params.vm_host == "kvm1"
    assert params.vm_action == "list"
    assert params.vm_target is None
