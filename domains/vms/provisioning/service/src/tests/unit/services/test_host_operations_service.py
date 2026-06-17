from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from db.models import Host
from models.ansible import ConnectivityResult
from models.jobs_model import JobSubmitResponse
from models.vm_request_model import VmActionRequest
from services.host_operations_service import HostOperationsService
from services.host_service import HostNotFoundError


def _host() -> Host:
    return Host(
        name="kvm1",
        kvm_host="10.0.0.1",
        public_host="host.example",
        ssh_user="ubuntu",
        ssh_key_type="path",
        ssh_key_value="/tmp/key",
        gpu_count=1,
        enabled=True,
    )


@pytest.mark.asyncio
async def test_check_capacity_requires_registered_host():
    host_service = MagicMock()
    host_service.get_host.return_value = None
    service = HostOperationsService(
        ansible_service=MagicMock(),
        host_service=host_service,
        job_service=MagicMock(),
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
        ansible_service=MagicMock(),
        host_service=host_service,
        job_service=job_service,
        job_queue_provider=lambda: job_queue,
    )

    response = await service.check_capacity(host="kvm1", body=VmActionRequest(max_retries=2))

    assert response.job_id == "job-1"
    params, queue = job_service.submit.await_args.args
    assert params.vm_host == "kvm1"
    assert params.vm_action == "check"
    assert params.vm_target is None
    assert params.max_retries == 2
    assert queue is job_queue


@pytest.mark.asyncio
async def test_check_connectivity_renders_temp_inventory_and_cleans_it_up(tmp_path: Path):
    inv_path = tmp_path / "inventory.ini"
    inv_path.write_text("[kvm_hosts]\nkvm1\n", encoding="utf-8")
    ansible_service = MagicMock()
    ansible_service.write_inventory.return_value = inv_path
    ansible_service.check_connectivity_with_inventory = AsyncMock(
        return_value=ConnectivityResult(host="kvm1", reachable=True, detail="pong")
    )
    host_service = MagicMock()
    host_service.get_host.return_value = _host()
    service = HostOperationsService(
        ansible_service=ansible_service,
        host_service=host_service,
        job_service=MagicMock(),
        job_queue_provider=lambda: object(),
    )

    result = await service.check_connectivity(host="kvm1")

    assert result.reachable is True
    ansible_service.write_inventory.assert_called_once()
    ansible_service.check_connectivity_with_inventory.assert_awaited_once_with("kvm1", inv_path)
    assert not inv_path.exists()
