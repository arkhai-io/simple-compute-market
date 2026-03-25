"""Mock provisioning client — test double with no I/O.

Returns deterministic static data without spawning subprocesses, making HTTP
calls, or touching the filesystem. Suitable for unit tests and CI runs where
no infrastructure is available.

Activate with PROVISIONING_MODE=mock.

Test-control hooks
------------------
Override module-level variables before calling any function:

    import service.clients.mock_provisioning as mp
    mp.PROVISION_RESULT = {"ssh_command": "ssh -p 9999 test@10.0.0.1", ...}
    mp.SHOULD_FAIL = True   # makes provision_machine_async raise ProvisioningJobError

Reset to defaults between tests by reassigning the originals or calling
_reset_defaults().
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from service.clients.provisioning import ProvisioningJobError

# ---------------------------------------------------------------------------
# Configurable defaults
# ---------------------------------------------------------------------------

PROVISION_RESULT: dict[str, Any] = {
    "ssh_command": "ssh -p 2222 tenant@127.0.0.1",
    "ssh_port": "2222",
    "tenant_user": "tenant",
    "vm_host_ip": "127.0.0.1",
    "authentication": {
        "root": {
            "password": "mock-root-password",
            "ssh_commands": {"default": "ssh -i /tmp/mock_key root@127.0.0.1"},
            "ssh_key_path_host": "/tmp/mock_key",
        },
        "tenant": {
            "password": "mock-tenant-password",
            "ssh_commands": {"default": "ssh -p 2222 tenant@127.0.0.1"},
            "key_type": "ed25519",
        },
    },
}

SHUTDOWN_RESULT: dict[str, Any] = {
    "status": "ok",
    "vm_host": "ww1",
    "vm_target": "tenant-vm",
}

RESOURCES_RESULT: dict[str, Any] = {
    "status": "ok",
    "vm_host": "ww1",
    "available": True,
    "running_vms": 0,
}

# Set to True to make provision_machine_async raise ProvisioningJobError
SHOULD_FAIL: bool = False

# How long (seconds) before a provisioned slot is auto-freed. Mirrors MOCK_RESOURCE_FREE_INTERVAL env var.
MOCK_RESOURCE_FREE_INTERVAL: int = int(os.getenv("MOCK_RESOURCE_FREE_INTERVAL", "60"))

# Internal: holds the pending auto-free task so it can be cancelled on reset or re-provision.
_last_provisioned_task: asyncio.Task | None = None


async def _free_resource_after(interval: int) -> None:
    """Sleep for *interval* seconds then flip the mock slot back to available."""
    await asyncio.sleep(interval)
    RESOURCES_RESULT["available"] = True
    RESOURCES_RESULT["running_vms"] = 0


def _reset_defaults() -> None:
    """Restore all module-level overrides to their original values."""
    global PROVISION_RESULT, SHUTDOWN_RESULT, RESOURCES_RESULT, SHOULD_FAIL, _last_provisioned_task
    # Cancel any pending auto-free task so it doesn't bleed across tests.
    # Wrapped in try-except because the event loop may already be closed when
    # this is called from synchronous test teardown fixtures.
    if _last_provisioned_task is not None and not _last_provisioned_task.done():
        try:
            _last_provisioned_task.cancel()
        except RuntimeError:
            pass  # event loop already closed — nothing to cancel
    _last_provisioned_task = None

    PROVISION_RESULT = {
        "ssh_command": "ssh -p 2222 tenant@127.0.0.1",
        "ssh_port": "2222",
        "tenant_user": "tenant",
        "vm_host_ip": "127.0.0.1",
        "authentication": {
            "root": {
                "password": "mock-root-password",
                "ssh_commands": {"default": "ssh -i /tmp/mock_key root@127.0.0.1"},
                "ssh_key_path_host": "/tmp/mock_key",
            },
            "tenant": {
                "password": "mock-tenant-password",
                "ssh_commands": {"default": "ssh -p 2222 tenant@127.0.0.1"},
                "key_type": "ed25519",
            },
        },
    }
    SHUTDOWN_RESULT = {"status": "ok", "vm_host": "ww1", "vm_target": "tenant-vm"}
    RESOURCES_RESULT = {"status": "ok", "vm_host": "ww1", "available": True, "running_vms": 0}
    SHOULD_FAIL = False


# ---------------------------------------------------------------------------
# Public interface (mirrors service.clients.provisioning)
# ---------------------------------------------------------------------------


async def provision_machine_async(
    provisioning_service_url: str,
    params: dict[str, Any],
    *,
    timeout: int = 3600,
    poll_interval: int = 15,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Return PROVISION_RESULT immediately (no I/O).

    Marks the resource slot as occupied and schedules an auto-free after
    MOCK_RESOURCE_FREE_INTERVAL seconds so the mock behaves like real modes.

    Raises ProvisioningJobError if SHOULD_FAIL is True.
    """
    global _last_provisioned_task
    if SHOULD_FAIL:
        raise ProvisioningJobError("mock failure")

    # Mark slot occupied so the resource poller reads the correct state.
    RESOURCES_RESULT["available"] = False
    RESOURCES_RESULT["running_vms"] = 1

    # Cancel any previously pending free (idempotent re-provision).
    if _last_provisioned_task is not None and not _last_provisioned_task.done():
        _last_provisioned_task.cancel()
    _last_provisioned_task = asyncio.create_task(_free_resource_after(MOCK_RESOURCE_FREE_INTERVAL))

    return dict(PROVISION_RESULT)


async def schedule_vm_shutdown_async(
    provisioning_service_url: str,
    lease_end_utc: str,
    vm_host: str = "ww1",
    vm_target: str = "tenant-vm",
    *,
    timeout: int = 300,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Return SHUTDOWN_RESULT merged with the provided lease_end_utc (no I/O)."""
    return dict(SHUTDOWN_RESULT) | {"lease_end_utc": lease_end_utc}


async def get_vm_available_resources(
    provisioning_service_url: str,
    vm_host: str = "ww1",
    *,
    timeout: int = 120,
    poll_interval: int = 5,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Return RESOURCES_RESULT with vm_host reflecting the argument (no I/O).

    The ``available`` field reflects live mock state: False immediately after
    provision_machine_async is called, True again after MOCK_RESOURCE_FREE_INTERVAL.
    """
    return dict(RESOURCES_RESULT) | {"vm_host": vm_host}
