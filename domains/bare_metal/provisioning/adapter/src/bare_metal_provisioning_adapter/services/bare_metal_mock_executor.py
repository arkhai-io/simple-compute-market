"""The bare-metal adapter's mock executor for the provisioning mock profile.

Grant and reclaim jobs run through the same job service, host check, inventory
rendering, and result parsing as a real run; only the playbook's execution is
replaced. Its default output is the ``node_grant_access_data`` or
``node_reclaim_access_data`` fact the bare-metal access role prints, rendered for
the job and the registered host it runs against, so the fulfillment provider reads
the same fields from it that it reads from a real run.

The instance has its own rules, installed through the bare-metal adapter's
``/test/bare-metal/mock-rules`` routes, so they never match a VM job.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from vm_provisioning_adapter.services.mock_ansible_service import (
    ProgrammableMockAnsibleService,
)

#: The tenant account a default grant reports when the job names none.
DEFAULT_MOCK_SSH_USER = "mocktenant"


class BareMetalMockAnsibleService(ProgrammableMockAnsibleService):
    """Mock runner whose default output is the bare-metal access fact."""

    def __init__(self, settings, **kwargs) -> None:
        super().__init__(settings, **kwargs)
        # The registered host record each job's inventory was rendered from,
        # keyed by host_id; a real grant reports that host's connection.
        self._hosts: dict[str, Any] = {}

    def write_inventory(self, hosts: list):
        for host in hosts:
            host_id = getattr(host, "host_id", None)
            if host_id:
                self._hosts[str(host_id)] = host
        return super().write_inventory(hosts)

    def default_stdout(self, run) -> str:
        params = getattr(run, "_params", None)
        if params is None:
            return super().default_stdout(run)
        action = params.executor_action or params.vm_action
        host = self._hosts.get(params.host_id)
        connection_host = getattr(host, "ssh_host", None) or params.host_id
        connection_port = getattr(host, "ssh_port", None) or 22
        common = {
            "action": action,
            "host_id": params.host_id,
            "physical_host_id": params.physical_host_id or "",
            "ssh_user": params.ssh_user or DEFAULT_MOCK_SSH_USER,
            "escrow_uid": params.escrow_uid or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "success",
        }
        if action == NODE_GRANT_ACCESS_ACTION:
            fact = "node_grant_access_data"
            data = {**common, "host": connection_host, "port": str(connection_port)}
        elif action == NODE_RECLAIM_ACCESS_ACTION:
            fact = "node_reclaim_access_data"
            data = {
                **common,
                "reclaim_policy": "remove_lease_key",
                "host": params.host_id,
                "account_locked": "false",
                "account_deleted": "false",
            }
        else:
            return super().default_stdout(run)
        return (
            "PLAY [Mock bare-metal access] **************************************\n\n"
            "TASK [debug] *******************************************************\n"
            f"ok: [{params.host_id}] => {{\n"
            f'    "{fact}": {json.dumps(data, indent=8)}\n'
            "}\n"
        )


__all__ = ["BareMetalMockAnsibleService", "DEFAULT_MOCK_SSH_USER"]
