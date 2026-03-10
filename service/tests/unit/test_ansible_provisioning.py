"""Unit tests for service.clients.ansible_provisioning helper functions."""
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_extract_external_port_json_format():
    from service.clients.ansible_provisioning import _extract_external_port
    output = 'some output {"external_ssh_port": "2222"} more output'
    assert _extract_external_port(output) == "2222"


def test_extract_external_port_ssh_format():
    from service.clients.ansible_provisioning import _extract_external_port
    output = "ssh command: -p 2200 user@192.168.1.1"
    assert _extract_external_port(output) == "2200"


def test_extract_external_port_none():
    from service.clients.ansible_provisioning import _extract_external_port
    assert _extract_external_port("no port here") is None


def test_extract_tenant_user():
    from service.clients.ansible_provisioning import _extract_tenant_user
    output = '{"tenant_user": "alice"}'
    assert _extract_tenant_user(output) == "alice"


def test_extract_tenant_user_none():
    from service.clients.ansible_provisioning import _extract_tenant_user
    assert _extract_tenant_user("nothing here") is None


def _make_proc(stdout: str, returncode: int = 0):
    """Create a mock asyncio subprocess that returns *stdout* and *returncode*."""
    proc = MagicMock()
    proc.returncode = returncode
    # communicate() is awaited, must be an AsyncMock
    proc.communicate = AsyncMock(return_value=(stdout.encode(), b""))
    proc.kill = MagicMock()
    return proc


@pytest.mark.asyncio
async def test_get_vm_available_resources_zero_vms():
    """virsh reports 0 running VMs → available=True, running_vms=0."""
    from service.clients.ansible_provisioning import get_vm_available_resources

    ansible_stdout = "ww1 | SUCCESS | rc=0 >>\n0\n"
    proc = _make_proc(ansible_stdout, returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await get_vm_available_resources("http://ignored", vm_host="ww1")

    assert result["status"] == "ok"
    assert result["vm_host"] == "ww1"
    assert result["available"] is True
    assert result["running_vms"] == 0


@pytest.mark.asyncio
async def test_get_vm_available_resources_one_vm():
    """virsh reports 1 running VM → available=False, running_vms=1."""
    from service.clients.ansible_provisioning import get_vm_available_resources

    ansible_stdout = "ww1 | SUCCESS | rc=0 >>\n1\n"
    proc = _make_proc(ansible_stdout, returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await get_vm_available_resources("http://ignored", vm_host="ww1")

    assert result["status"] == "ok"
    assert result["vm_host"] == "ww1"
    assert result["available"] is False
    assert result["running_vms"] == 1


@pytest.mark.asyncio
async def test_get_vm_available_resources_multiple_vms():
    """virsh reports multiple running VMs → available=False, running_vms matches count."""
    from service.clients.ansible_provisioning import get_vm_available_resources

    ansible_stdout = "ww1 | SUCCESS | rc=0 >>\n3\n"
    proc = _make_proc(ansible_stdout, returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await get_vm_available_resources("http://ignored", vm_host="ww1")

    assert result["available"] is False
    assert result["running_vms"] == 3


@pytest.mark.asyncio
async def test_get_vm_available_resources_ansible_failure():
    """Non-zero exit code from Ansible raises CalledProcessError."""
    from service.clients.ansible_provisioning import get_vm_available_resources

    proc = _make_proc("", returncode=2)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(subprocess.CalledProcessError):
            await get_vm_available_resources("http://ignored", vm_host="ww1")
