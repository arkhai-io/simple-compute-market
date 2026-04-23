"""Mock implementation of AnsibleService for use in the provisioning service's
'mock' ACTIVE_PROFILE.

Activated when ACTIVE_PROFILES includes 'mock'.  Returns deterministic
fake results with no subprocess invocations, no SSH, and no filesystem I/O
beyond reading the configured inventory path.

The mock is the provisioning service's responsibility, not the agent's.
Agents always call the provisioning service HTTP API; whether that service
runs real Ansible or this mock is a deployment concern controlled by the
ACTIVE_PROFILES environment variable on the provisioning service container.

Control hooks (constructor parameters)
---------------------------------------
``provision_result`` — dict returned as the parsed result for any create job.
``should_fail``      — if True, ``wait_for_playbook`` raises AnsibleError.
``fail_message``     — error string used when should_fail is True.
``host_ip``          — value returned by ``lookup_host_ip`` for any host.

These are set once at construction.  For docker-compose e2e tests that need
to toggle failure mode, run two separate provisioning-service containers
configured with different profiles.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

from models.ansible import ConnectivityResult, InventoryHost, InventoryResponse
from models.jobs_model import AnsibleJobParams, AnsibleRunResult
from services.ansible_service import AnsibleError, AnsibleResult, AnsibleRun

logger = logging.getLogger(__name__)

_FAKE_STDOUT = """\
PLAY [Mock Provision] *********************************************************

TASK [debug] ******************************************************************
ok: [ww1] => {
    "vm_creation_data": {
        "action": "create",
        "vm_name": "mock-vm",
        "status": "running",
        "host": "ww1",
        "timestamp": "2025-01-01T00:00:00Z",
        "tenant_user": "mockuser",
        "external_ssh_port": "2222",
        "vm_ip_internal": "192.168.122.2",
        "authentication": {
            "tenant": {
                "password": "mock-tenant-password",
                "key_type": "generated",
                "ssh_commands": {
                    "internal": "ssh -i key mockuser@192.168.122.2",
                    "external": "ssh -i key -p 2222 mockuser@127.0.0.1"
                }
            },
            "root": {
                "password": "mock-root-password",
                "ssh_commands": {"internal": "ssh root@192.168.122.2"},
                "ssh_key_path_host": "/root/.ssh/mock-vm_root_ed25519"
            }
        }
    }
}
"""


class MockAnsibleService:
    """Drop-in replacement for AnsibleService that performs no I/O.

    Implements the same interface as AnsibleService so AnsibleJobService
    can use it without modification.
    """

    def __init__(
        self,
        settings,
        *,
        provision_result: Optional[str] = None,
        should_fail: bool = False,
        fail_message: str = "mock failure",
        host_ip: str = "127.0.0.1",
    ) -> None:
        self._settings = settings
        self._stdout = provision_result or _FAKE_STDOUT
        self._should_fail = should_fail
        self._fail_message = fail_message
        self._host_ip = host_ip

    # ------------------------------------------------------------------
    # Playbook interface — mirrors AnsibleService exactly
    # ------------------------------------------------------------------

    def build_vars_file(self, params: AnsibleJobParams) -> Path:
        """Return a dummy path — no file is written."""
        return Path(f"/tmp/mock_vars_{params.vm_action}.yml")

    def start_playbook(
        self,
        playbook_path: Path,
        inventory_path: Path,
        extra_vars_path: Path,
        limit: str,
        extra_cli_vars: dict | None = None,
    ) -> AnsibleRun:
        """Return a fake AnsibleRun handle with a mock process."""
        mock_proc = MagicMock()
        mock_proc.pid = 0
        mock_proc.poll.return_value = 0
        return AnsibleRun(
            process=mock_proc,
            process_id=0,
            vars_path=extra_vars_path,
        )

    async def wait_for_playbook(
        self,
        run: AnsibleRun,
        timeout_seconds: int,
        log_callback: Optional[Callable] = None,
    ) -> AnsibleResult:
        """Return a fake result immediately (no subprocess, no wait)."""
        await asyncio.sleep(0)  # yield to event loop

        if self._should_fail:
            raise AnsibleError(self._fail_message, stdout="", stderr=self._fail_message)

        if log_callback:
            try:
                await asyncio.to_thread(log_callback, self._stdout, "")
            except Exception:
                pass

        return AnsibleResult(
            stdout=self._stdout,
            stderr="",
            process_id=0,
        )

    def parse_playbook_result(
        self, result: AnsibleResult, params: AnsibleJobParams
    ) -> AnsibleRunResult:
        """Delegate to real parsing logic — only subprocess boundary is mocked."""
        from services.ansible_service import AnsibleService
        real = AnsibleService.__new__(AnsibleService)
        real._settings = self._settings
        return real.parse_playbook_result(result, params)

    # ------------------------------------------------------------------
    # Inventory interface
    # ------------------------------------------------------------------

    def parse_inventory(self, search: str | None = None) -> list[InventoryHost]:
        """Return a single fake host entry."""
        hosts = [
            InventoryHost(
                name="ww1",
                ansible_host=self._host_ip,
                vars={"ansible_ssh_private_key_file": "~/.ssh/id_ed25519"},
            )
        ]
        if search:
            hosts = [h for h in hosts if search.lower() in h.name.lower()]
        return hosts

    def get_inventory(self, search: str | None = None) -> InventoryResponse:
        return InventoryResponse(
            inventory_path=str(getattr(self._settings, "resolved_inventory_path", "/mock/hosts")),
            hosts=self.parse_inventory(search=search),
        )

    def lookup_host_ip(self, vm_host: str) -> Optional[str]:
        return self._host_ip

    # ------------------------------------------------------------------
    # Connectivity check
    # ------------------------------------------------------------------

    async def check_connectivity(self, host: str) -> ConnectivityResult:
        """Always reports reachable in mock mode."""
        await asyncio.sleep(0)
        return ConnectivityResult(
            host=host,
            reachable=True,
            detail="mock: connectivity check always succeeds",
        )
