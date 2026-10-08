"""The output a bare-metal access job produces under the mock profile.

The mock Ansible runner renders a run's output, when no rule replaces it, with
the function a domain contributes; this is bare metal's. It is the
``node_grant_access_data`` or ``node_reclaim_access_data`` fact the access role
prints, rendered for the job and the registered host it runs against, so the
codec and the fulfillment provider read the same fields from it that they read
from a real run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from compute_provisioning_ansible import MockPlaybook

from bare_metal_provisioning_adapter.codec import (
    BARE_METAL_RESULT_FACTS,
    DEFAULT_BARE_METAL_RECLAIM_POLICY,
    BareMetalJobParams,
)

#: The tenant account a default grant reports when the job names none.
DEFAULT_MOCK_SSH_USER = "mocktenant"


def bare_metal_mock_output(playbook: MockPlaybook) -> str:
    """The access fact a successful grant or reclaim of this job prints."""
    params = BareMetalJobParams.model_validate(dict(playbook.parameters))
    host = playbook.host
    data = {
        "action": params.action,
        "host_id": params.host_id,
        "physical_host_id": params.physical_host_id or "",
        "ssh_user": params.ssh_user or DEFAULT_MOCK_SSH_USER,
        "escrow_uid": params.escrow_uid or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "success",
    }
    if params.action == NODE_GRANT_ACCESS_ACTION:
        # A grant reports the address the buyer connects to: the registered
        # host's connection.
        data["host"] = (host.ssh_host if host is not None else None) or params.host_id
        data["port"] = str((host.ssh_port if host is not None else None) or 22)
    else:
        data.update(
            reclaim_policy=params.reclaim_policy or DEFAULT_BARE_METAL_RECLAIM_POLICY,
            host=params.host_id,
            account_locked="false",
            account_deleted="false",
        )
    fact = BARE_METAL_RESULT_FACTS[params.action]
    return (
        "PLAY [Mock bare-metal access] **************************************\n\n"
        "TASK [debug] *******************************************************\n"
        f"ok: [{params.host_id}] => {{\n"
        f'    "{fact}": {json.dumps(data, indent=8)}\n'
        "}\n"
    )


__all__ = ["DEFAULT_MOCK_SSH_USER", "bare_metal_mock_output"]
