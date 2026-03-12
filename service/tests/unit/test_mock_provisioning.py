"""Unit tests for service.clients.mock_provisioning (test double)."""
import asyncio
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


@pytest.mark.asyncio
async def test_provision_marks_slot_unavailable():
    """provision_machine_async flips available=False so the poller sees the correct state."""
    assert mp.RESOURCES_RESULT["available"] is True

    await mp.provision_machine_async("http://ignored", {})

    resources = await mp.get_vm_available_resources("http://ignored", vm_host="ww1")
    assert resources["available"] is False
    assert resources["running_vms"] == 1


@pytest.mark.asyncio
async def test_provision_schedules_auto_free():
    """After MOCK_RESOURCE_FREE_INTERVAL elapses the slot becomes available again."""
    original_interval = mp.MOCK_RESOURCE_FREE_INTERVAL
    mp.MOCK_RESOURCE_FREE_INTERVAL = 0  # instant release for test speed

    await mp.provision_machine_async("http://ignored", {})
    assert mp.RESOURCES_RESULT["available"] is False

    # Allow the event loop to run the scheduled task
    await asyncio.sleep(0.05)

    assert mp.RESOURCES_RESULT["available"] is True
    assert mp.RESOURCES_RESULT["running_vms"] == 0

    mp.MOCK_RESOURCE_FREE_INTERVAL = original_interval


@pytest.mark.asyncio
async def test_reprovision_cancels_previous_free_task():
    """Re-provisioning cancels any pending free task and schedules a new one."""
    mp.MOCK_RESOURCE_FREE_INTERVAL = 100  # long enough not to fire during test

    await mp.provision_machine_async("http://ignored", {})
    first_task = mp._last_provisioned_task

    await mp.provision_machine_async("http://ignored", {})
    second_task = mp._last_provisioned_task

    # Yield the event loop so the CancelledError propagates and task reaches done state.
    await asyncio.sleep(0)

    assert first_task is not None
    assert second_task is not None
    assert first_task is not second_task
    assert first_task.cancelled()


@pytest.mark.asyncio
async def test_reset_defaults_cancels_pending_task():
    """_reset_defaults() cancels the auto-free task and restores available=True."""
    mp.MOCK_RESOURCE_FREE_INTERVAL = 100

    await mp.provision_machine_async("http://ignored", {})
    task = mp._last_provisioned_task
    assert mp.RESOURCES_RESULT["available"] is False

    mp._reset_defaults()

    # Yield the event loop so the CancelledError propagates and task reaches done state.
    await asyncio.sleep(0)

    assert mp.RESOURCES_RESULT["available"] is True
    assert mp._last_provisioned_task is None
    assert task is not None and task.cancelled()
