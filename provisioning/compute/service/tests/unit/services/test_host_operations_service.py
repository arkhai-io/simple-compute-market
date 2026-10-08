"""VM's host operation: the capacity check job.

Connectivity is the family's host route service, probing through each kind's
probe; the Ansible probe is the Ansible distribution's, tested there.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning.jobs.submission import JobSubmissionService
from compute_provisioning_contracts import JobSubmitResponse
from vm_provisioning_adapter.services.host_operations_service import HostOperationsService
from vm_provisioning_operator.models import VmActionRequest


def _service(*registered: str) -> tuple[HostOperationsService, MagicMock]:
    engine = MagicMock()
    engine.submit = AsyncMock(return_value=JobSubmitResponse(job_id="job-1", status="queued"))
    hosts = SimpleNamespace(
        get_host=lambda host_id: (
            SimpleNamespace(host_id=host_id, enabled=True) if host_id in registered else None
        )
    )
    submission = JobSubmissionService(engine=engine, hosts=hosts, job_queue_provider=lambda: "q")
    return HostOperationsService(submission=submission), engine


@pytest.mark.asyncio
async def test_check_capacity_requires_registered_host():
    service, engine = _service()

    with pytest.raises(HostNotFoundError):
        await service.check_capacity(host="ghost", body=VmActionRequest())
    engine.submit.assert_not_called()


@pytest.mark.asyncio
async def test_check_capacity_submits_a_check_job_on_the_host():
    service, engine = _service("kvm1")

    response = await service.check_capacity(host="kvm1", body=VmActionRequest(max_retries=2))

    assert response.job_id == "job-1"
    submitted = engine.submit.await_args.kwargs
    assert (submitted["host_id"], submitted["action"]) == ("kvm1", "check")
    assert submitted["params"]["vm_target"] is None
    assert submitted["max_retries"] == 2
    assert submitted["job_queue"] == "q"
