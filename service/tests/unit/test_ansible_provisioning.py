"""Unit tests for service.clients.ansible_provisioning helper functions."""
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


@pytest.mark.asyncio
async def test_get_vm_available_resources():
    from service.clients.ansible_provisioning import get_vm_available_resources
    result = await get_vm_available_resources("http://ignored", vm_host="ww1")
    assert result["status"] == "ok"
    assert result["vm_host"] == "ww1"
    assert result["available"] is True
