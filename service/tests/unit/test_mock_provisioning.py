"""Unit tests for service.clients.mock_provisioning (test double)."""
import pytest
import service.clients.mock_provisioning as mp


@pytest.fixture(autouse=True)
def reset_mock_state():
    """Restore module-level defaults after every test."""
    yield
    mp._reset_defaults()


@pytest.mark.asyncio
async def test_provision_returns_default_result():
    result = await mp.provision_machine_async("http://ignored", {})
    assert result["ssh_command"] == "ssh -p 2222 tenant@127.0.0.1"
    assert result["ssh_port"] == "2222"
    assert result["tenant_user"] == "tenant"
    assert result["vm_host_ip"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_provision_raises_on_should_fail():
    from service.clients.provisioning import ProvisioningJobError
    mp.SHOULD_FAIL = True
    with pytest.raises(ProvisioningJobError, match="mock failure"):
        await mp.provision_machine_async("http://ignored", {})


@pytest.mark.asyncio
async def test_provision_returns_override_result():
    mp.PROVISION_RESULT = {
        "ssh_command": "ssh -p 9999 test@10.0.0.1",
        "ssh_port": "9999",
        "tenant_user": "test",
        "vm_host_ip": "10.0.0.1",
    }
    result = await mp.provision_machine_async("http://ignored", {})
    assert result["ssh_port"] == "9999"
    assert result["vm_host_ip"] == "10.0.0.1"


@pytest.mark.asyncio
async def test_shutdown_includes_lease_end():
    result = await mp.schedule_vm_shutdown_async(
        "http://ignored", "2025-01-01 12:00", vm_host="ww2", vm_target="my-vm"
    )
    assert result["lease_end_utc"] == "2025-01-01 12:00"
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_resources_returns_correct_vm_host():
    result = await mp.get_vm_available_resources("http://ignored", vm_host="ww3")
    assert result["vm_host"] == "ww3"
    assert result["status"] == "ok"
    assert result["available"] is True
