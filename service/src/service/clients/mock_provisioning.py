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
}

# Set to True to make provision_machine_async raise ProvisioningJobError
SHOULD_FAIL: bool = False


def _reset_defaults() -> None:
    """Restore all module-level overrides to their original values."""
    global PROVISION_RESULT, SHUTDOWN_RESULT, RESOURCES_RESULT, SHOULD_FAIL
    PROVISION_RESULT = {
        "ssh_command": "ssh -p 2222 tenant@127.0.0.1",
        "ssh_port": "2222",
        "tenant_user": "tenant",
        "vm_host_ip": "127.0.0.1",
    }
    SHUTDOWN_RESULT = {"status": "ok", "vm_host": "ww1", "vm_target": "tenant-vm"}
    RESOURCES_RESULT = {"status": "ok", "vm_host": "ww1", "available": True}
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

    Raises ProvisioningJobError if SHOULD_FAIL is True.
    """
    if SHOULD_FAIL:
        raise ProvisioningJobError("mock failure")
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
    """Return RESOURCES_RESULT with vm_host reflecting the argument (no I/O)."""
    return dict(RESOURCES_RESULT) | {"vm_host": vm_host}
