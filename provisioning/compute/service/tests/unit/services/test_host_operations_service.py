from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost
from compute_provisioning.hosts.service import HostNotFoundError
from compute_provisioning_service.db.models import Host
from compute_provisioning_ansible.runner import ConnectivityResult
from vm_provisioning_operator.models import VmActionRequest
from compute_provisioning.jobs import JobSubmitResponse
from vm_provisioning_adapter.services.host_operations_service import HostOperationsService

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
    assert params.host_id == "kvm1"
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
    host_service.lookup.return_value = _execution_host()
    service = HostOperationsService(
        ansible_service=ansible_service,
        host_service=host_service,
        job_service=MagicMock(),
        job_queue_provider=lambda: object(),
    )

    result = await service.check_connectivity(host="kvm1")

    assert result.reachable is True
    (target,) = ansible_service.write_inventory.call_args.args[0]
    assert (target.host_id, target.ssh_host, target.ssh_user) == ("kvm1", "10.0.0.1", "ubuntu")
    assert (target.ssh_key_type, target.ssh_key_value) == ("path", "/tmp/key")
    ansible_service.check_connectivity_with_inventory.assert_awaited_once_with("kvm1", inv_path)
    assert not inv_path.exists()
