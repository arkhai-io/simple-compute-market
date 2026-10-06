from unittest.mock import AsyncMock, MagicMock

import pytest

from vm_provisioning_operator.models import CreateVmRequest, VmActionRequest
from compute_provisioning_contracts import JobSubmitResponse
from vm_provisioning_adapter.services.vm_operations_service import VmOperationsService


def _service(job_id: str) -> tuple[VmOperationsService, MagicMock]:
    submission = MagicMock()
    submission.submit = AsyncMock(return_value=JobSubmitResponse(job_id=job_id, status="queued"))
    return VmOperationsService(submission=submission), submission


@pytest.mark.asyncio
async def test_create_vm_submits_create_params_under_the_request_operation():
    service, submission = _service("job-1")

    body = CreateVmRequest(vm_target="vm-1", vm_ram=2048, vm_vcpus=2)
    response = await service.create_vm(host="kvm1", body=body, operation_id="op-1")

    assert response.job_id == "job-1"
    submitted = submission.submit.await_args.kwargs
    assert (submitted["host_id"], submitted["action"]) == ("kvm1", "create")
    assert submitted["operation_id"] == "op-1"
    assert "contract" not in submitted
    assert submitted["params"]["vm_target"] == "vm-1"
    assert submitted["params"]["vm_ram"] == 2048


@pytest.mark.asyncio
async def test_submit_action_builds_simple_vm_action_params():
    service, submission = _service("job-2")

    await service.submit_action(
        action="reboot",
        host="kvm1",
        vm_name="vm-1",
        body=VmActionRequest(max_retries=4),
    )

    submitted = submission.submit.await_args.kwargs
    assert (submitted["host_id"], submitted["action"]) == ("kvm1", "reboot")
    assert submitted["params"]["vm_target"] == "vm-1"
    assert submitted["max_retries"] == 4


@pytest.mark.asyncio
async def test_list_vms_builds_host_scoped_params_without_vm_target():
    service, submission = _service("job-3")

    await service.list_vms(host="kvm1", body=VmActionRequest())

    submitted = submission.submit.await_args.kwargs
    assert (submitted["host_id"], submitted["action"]) == ("kvm1", "list")
    assert submitted["params"]["vm_target"] is None
