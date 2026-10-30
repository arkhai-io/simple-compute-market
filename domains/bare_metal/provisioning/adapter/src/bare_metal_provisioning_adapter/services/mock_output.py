"""The output a bare-metal access job produces under the mock profile.

The mock Ansible runner renders a run's output, when no rule replaces it, with
the function a domain contributes; this is bare metal's. It is the
``node_grant_access_data`` or ``node_reclaim_access_data`` fact the access role
prints, rendered for the job and the registered host it runs against, in the
form the packaged Ansible configuration prints it: the ``debug: var:`` fact in
the YAML result format, then the ``debug: msg:`` JSON copy as a literal block.
So the codec reads it through the same path, and the fulfillment provider the
same fields, as from a real run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION
from compute_provisioning_ansible import MockPlaybook

from bare_metal_provisioning_adapter.codec import (
    BARE_METAL_RESULT_FACTS,
    DEFAULT_BARE_METAL_RECLAIM_POLICY,
    BareMetalJobParams,
)

#: The tenant account a default output names when the job names none. The role
#: refuses such a grant, and a fact naming this account matches no account the
#: job names, so the grant yields no evidence.
DEFAULT_MOCK_SSH_USER = "mocktenant"


def bare_metal_mock_output(playbook: MockPlaybook) -> str:
    """The access fact a successful grant or reclaim of this job prints."""
    params = BareMetalJobParams.model_validate(dict(playbook.parameters))
    host = playbook.host
    data: dict[str, str | bool] = {
        "action": params.action,
        "host_id": params.host_id,
        "physical_host_id": params.physical_host_id or "",
        "ssh_user": params.ssh_user or DEFAULT_MOCK_SSH_USER,
        "escrow_uid": params.escrow_uid or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "success",
    }
    if params.action == NODE_GRANT_ACCESS_ACTION:
        # A grant prints the provisioner's route to the host, as the role
        # prints its inventory's ansible_host and ansible_port; the buyer's
        # endpoint is the codec's, built from the host record.
        data["host"] = (host.ssh_host if host is not None else None) or params.host_id
        data["port"] = str((host.ssh_port if host is not None else None) or 22)
    else:
        # A default reclaim stands for one of a delivered grant, so its account
        # was present; a reclaim of an account never created arms a rule. It
        # neither locks nor deletes the account, as the default policy does not.
        # The role prints all three account fields as booleans.
        data.update(
            reclaim_policy=params.reclaim_policy or DEFAULT_BARE_METAL_RECLAIM_POLICY,
            host=params.host_id,
            account_present=True,
            account_locked=False,
            account_deleted=False,
        )
    return shipped_output(params.host_id, BARE_METAL_RESULT_FACTS[params.action], data)


def shipped_output(host_id: str, fact_name: str, fact: Mapping[str, str | bool]) -> str:
    """A run printing ``fact`` as the access role does under the packaged
    configuration's YAML result format.

    The ``var:`` fact's YAML is display only, each value quoted but a boolean;
    the ``msg:`` block is the role's ``to_nice_json`` copy, which is what is
    read.
    """
    yaml_lines = [f"        {name}: {_quoted(value)}" for name, value in sorted(fact.items())]
    json_lines = [f"        {line}" for line in json.dumps(fact, indent=4).splitlines()]
    return "\n".join(
        [
            "PLAY [Mock bare-metal access] **************************************",
            "",
            "TASK [Output access data as parsable JSON] *************************",
            f"ok: [{host_id}] => ",
            f"    {fact_name}:",
            *yaml_lines,
            "",
            "TASK [Output access JSON string for external parsing] **************",
            f"ok: [{host_id}] => ",
            "    msg: |-",
            *json_lines,
            "",
        ]
    )


def _quoted(value: str | bool) -> str:
    """``value`` as a YAML scalar: a boolean bare, anything else single-quoted."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "'" + str(value).replace("'", "''") + "'"


__all__ = ["DEFAULT_MOCK_SSH_USER", "bare_metal_mock_output", "shipped_output"]
