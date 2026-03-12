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


@pytest.mark.asyncio
async def test_get_vm_available_resources_host_not_in_inventory():
    """Empty Ansible output (host not in inventory) raises CalledProcessError, not available=True."""
    from service.clients.ansible_provisioning import get_vm_available_resources

    proc = _make_proc("", returncode=0)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(subprocess.CalledProcessError):
            await get_vm_available_resources("http://ignored", vm_host="vm1")


# ── Bug fix: FRP external ssh_command used in connection_details ──────────────

_PLAYBOOK_STDOUT_WITH_FRP = """
PLAY [Provision VM] ***

TASK [create vm] ***
ok: [ww1]

ww1 | SUCCESS => {
    "external_ssh_port": "7002",
    "tenant_user": "tenant3768"
}

"vm_creation_data": {
    "action": "create",
    "authentication": {
        "root": {
            "password": "rootpass",
            "ssh_commands": {
                "external": "ssh -i ~/.ssh/root_key -p 7002 root@abc123.arkhainet.whitewidget.tech",
                "internal": "ssh -i ~/.ssh/root_key root@192.168.122.75"
            },
            "ssh_key_path_host": "~/.ssh/root_key"
        },
        "tenant": {
            "key_type": "provided",
            "password": "tenantpass",
            "ssh_commands": {
                "external": "ssh -i <your_private_key> -p 7002 tenant3768@abc123.arkhainet.whitewidget.tech",
                "internal": "ssh -i <your_private_key> tenant3768@192.168.122.75"
            }
        }
    }
}
"""


@pytest.mark.asyncio
async def test_provision_machine_frp_uses_external_ssh_command():
    """When frp_domain is present, ssh_command and vm_host_ip use the FRP external address."""
    import json
    from pathlib import Path
    from service.clients.ansible_provisioning import provision_machine_async

    proc = _make_proc(_PLAYBOOK_STDOUT_WITH_FRP, returncode=0)

    fake_root = Path("/fake/root")
    params = {
        "ssh_pubkey": "ssh-ed25519 AAAA test",
        "vm_host": "ww1",
        "vm_target": "tenant-vm",
        "frp_server_addr": "frp.example.com",
        "frp_domain": "arkhainet.whitewidget.tech",
    }

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)), \
         patch("service.clients.ansible_provisioning._find_project_root", return_value=fake_root), \
         patch("service.clients.ansible_provisioning._lookup_vm_host_ip", return_value="10.161.42.195"), \
         patch("service.clients.ansible_provisioning._find_management_vars", return_value=fake_root / "management-vars.yaml"):
        result = await provision_machine_async("http://ignored", params)

    assert result["ssh_command"] == "ssh -i <your_private_key> -p 7002 tenant3768@abc123.arkhainet.whitewidget.tech"
    assert result["vm_host_ip"] == "abc123.arkhainet.whitewidget.tech"


@pytest.mark.asyncio
async def test_provision_machine_no_frp_uses_inventory_ip():
    """Without frp_domain, ssh_command and vm_host_ip fall back to inventory IP."""
    from pathlib import Path
    from service.clients.ansible_provisioning import provision_machine_async

    proc = _make_proc(_PLAYBOOK_STDOUT_WITH_FRP, returncode=0)

    fake_root = Path("/fake/root")
    params = {
        "ssh_pubkey": "ssh-ed25519 AAAA test",
        "vm_host": "ww1",
        "vm_target": "tenant-vm",
        # no frp_domain
    }

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)), \
         patch("service.clients.ansible_provisioning._find_project_root", return_value=fake_root), \
         patch("service.clients.ansible_provisioning._lookup_vm_host_ip", return_value="10.161.42.195"), \
         patch("service.clients.ansible_provisioning._find_management_vars", return_value=fake_root / "management-vars.yaml"):
        result = await provision_machine_async("http://ignored", params)

    assert result["vm_host_ip"] == "10.161.42.195"
    assert "abc123.arkhainet.whitewidget.tech" not in (result["ssh_command"] or "")
