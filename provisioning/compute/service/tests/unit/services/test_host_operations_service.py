"""VM's host operation: the capacity check job.

Connectivity is the family's host route service, probing through each kind's
probe; the Ansible probe is the Ansible distribution's, tested there.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning_contracts import JobSubmitResponse
from compute_provisioning_service.db.models import Host
from vm_provisioning_adapter.services.host_operations_service import HostOperationsService
from vm_provisioning_operator.models import VmActionRequest

_CONNECTION = ConnectionEnvelope(
    kind="ssh",
    version=1,
    public={
        "ssh_host": "10.0.0.1",
        "public_host": "host.example",
        "ssh_port": 22,
        "ssh_user": "ubuntu",
        "key_path": "/tmp/key",
    },
)


def _host() -> Host:
    host = Host(host_id="kvm1", gpu_count=1, enabled=True)
    host.set_connection(_CONNECTION)
    return host


def _execution_host() -> ExecutionHost:
    return ExecutionHost(host_id="kvm1", pool_id="default", connection=_CONNECTION)


@pytest.mark.asyncio
async def test_check_capacity_requires_registered_host():
    host_service = MagicMock()
    host_service.get_host.return_value = None
    service = HostOperationsService(
        host_service=host_service,
        job_submitter=MagicMock(),
        job_queue_provider=lambda: object(),
    )

    with pytest.raises(HostNotFoundError):
        await service.check_capacity(host="ghost", body=VmActionRequest())


@pytest.mark.asyncio
async def test_check_capacity_submits_check_job_to_resolved_queue():
    job_queue = object()
    host_service = MagicMock()
    host_service.get_host.return_value = _host()
    job_service = MagicMock()
    job_service.submit = AsyncMock(return_value=JobSubmitResponse(job_id="job-1", status="queued"))
    service = HostOperationsService(
        host_service=host_service,
        job_submitter=job_service,
        job_queue_provider=lambda: job_queue,
    )

    response = await service.check_capacity(host="kvm1", body=VmActionRequest(max_retries=2))

    assert response.job_id == "job-1"
    params, queue = job_service.submit.await_args.args
    assert params.host_id == "kvm1"
    assert params.vm_action == "check"
    assert params.vm_target is None
    assert params.max_retries == 2
    assert queue is job_queue
