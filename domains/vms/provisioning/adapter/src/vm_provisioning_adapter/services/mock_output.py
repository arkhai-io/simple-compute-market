"""The output a VM job produces under the mock profile when no rule replaces it.

The mock Ansible runner renders a run's output, when no rule replaces it, with
the function a domain contributes; this is VM's. It is the fact the
VM-operations role prints for the job's action, rendered for the job from its
stored parameters, in the form the packaged Ansible configuration prints it:
the ``debug: var:`` fact in the YAML result format, then the ``debug: msg:``
JSON copy as a literal block. So the codec reads it through the same path, and
the fulfillment provider the same fields, as from a real run.

A create prints the fact for the key the job carries: the buyer's own key when
the job names one, as every marketplace create does, else a key generated on
the host. It reports a forwarded port and no relay: a relay's address is filled
in only when a job runs and is not among its stored parameters, so a
relay-backed case states its output in a rule.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from compute_provisioning_ansible import MockPlaybook

from vm_provisioning_adapter.codec import VM_RESULT_FACTS, vm_job_params

#: The port a mocked create reports forwarding to the guest's SSH port.
MOCK_FORWARDED_PORT = "2222"
#: The guest's internal address a mocked create reports.
MOCK_GUEST_ADDRESS = "192.168.122.2"


def vm_mock_output(playbook: MockPlaybook) -> str:
    """The fact a successful run of this job prints, for its own guest."""
    params = vm_job_params(playbook.parameters, host_id=playbook.limit)
    guest = params.vm_target or params.executor_target or ""
    host = playbook.host
    tenant_host = (host.public_host or host.ssh_host) if host is not None else playbook.limit
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if params.vm_action == "create":
        fact = _create_fact(guest, tenant_host, timestamp, provided_key=params.ssh_pubkey)
    else:
        fact = {
            "action": params.vm_action,
            "vm_name": guest,
            "timestamp": timestamp,
            "host": playbook.limit,
            "status": "success",
        }
        if params.vm_action == "vm_remove":
            # A default remove stands for a delivered guest's: its create wrote
            # the cleanup script, which ran. The role prints booleans as text.
            fact.update(
                cleanup_record="true",
                guest_present="true",
                destroy_output="",
                cleanup_output=[],
                error="",
            )
    fact_name = VM_RESULT_FACTS.get(params.vm_action, f"vm_{params.vm_action}_data")
    return shipped_output(playbook.limit, fact_name, fact)


def tenant_account(guest: str) -> str:
    """The tenant account the role creates for ``guest``: its name with every
    character but a letter or digit removed, lower-cased."""
    return re.sub(r"[^a-zA-Z0-9]", "", guest).lower()


def _create_fact(
    guest: str, tenant_host: str, timestamp: str, *, provided_key: str | None
) -> dict[str, Any]:
    user = tenant_account(guest)
    port = MOCK_FORWARDED_PORT
    if provided_key:
        tenant = {
            "password": "mock-tenant-password",
            "key_type": "provided",
            "public_key": provided_key,
            "ssh_commands": {
                "internal": f"ssh -i <your_private_key> {user}@{MOCK_GUEST_ADDRESS}",
                "external": f"ssh -i <your_private_key> -p {port} {user}@{tenant_host}",
            },
        }
    else:
        tenant = {
            "password": "mock-tenant-password",
            "key_type": "generated",
            "ssh_key_path_host": f"~/.ssh/{guest}_tenant_ed25519",
            "ssh_commands": {
                "internal": f"ssh -i keys/{guest}_tenant_private_key {user}@{MOCK_GUEST_ADDRESS}",
                "external": f"ssh -i keys/{guest}_tenant_private_key -p {port} {user}@{tenant_host}",
            },
        }
    no_relay = {"enabled": False, "relay_addr": "N/A", "remote_port": "N/A", "ssh_access": "N/A"}
    return {
        "action": "create",
        "vm_name": guest,
        "timestamp": timestamp,
        "host": tenant_host,
        "status": "success",
        "vm_state": "running",
        "vm_ip_internal": MOCK_GUEST_ADDRESS,
        "external_ssh_port": port,
        "tenant_user": user,
        "authentication": {
            "root": {
                "password": "mock-root-password",
                "ssh_key_path_host": f"~/.ssh/{guest}_root_ed25519",
                "ssh_commands": {"internal": f"ssh root@{MOCK_GUEST_ADDRESS}"},
            },
            "tenant": tenant,
        },
        "network": {
            "mode": "direct_port_forwarding",
            "port_forwarding": f"{tenant_host}:{port} -> {MOCK_GUEST_ADDRESS}:22",
        },
        # The provided-key fact names its relay block ``frp``; the generated-key
        # fact names it ``relay``.
        ("frp" if provided_key else "relay"): no_relay,
    }


def shipped_output(host_id: str, fact_name: str, fact: Mapping[str, Any]) -> str:
    """A run printing ``fact`` as the VM role does under the packaged
    configuration's YAML result format.

    The ``var:`` fact's YAML is display only; the ``msg:`` block is the role's
    ``to_nice_json`` copy, which is what is read.
    """
    json_lines = [f"        {line}" for line in json.dumps(fact, indent=4).splitlines()]
    return "\n".join(
        [
            "PLAY [Mock VM operations] ******************************************",
            "",
            "TASK [Output VM data as parsable JSON] *****************************",
            f"ok: [{host_id}] => ",
            f"    {fact_name}:",
            *_yaml_lines(fact, 8),
            "",
            "TASK [Output VM JSON string for external parsing] ******************",
            f"ok: [{host_id}] => ",
            "    msg: |-",
            *json_lines,
            "",
        ]
    )


def _yaml_lines(value: Any, indent: int) -> list[str]:
    """``value`` as indented block YAML, scalars single-quoted."""
    pad = " " * indent
    lines: list[str] = []
    if isinstance(value, Mapping):
        for name, item in value.items():
            if isinstance(item, (Mapping, list)) and item:
                lines.append(f"{pad}{name}:")
                lines.extend(_yaml_lines(item, indent + 4))
            else:
                lines.append(f"{pad}{name}: {_scalar(item)}")
    else:
        for item in value:
            if isinstance(item, (Mapping, list)) and item:
                lines.append(f"{pad}-")
                lines.extend(_yaml_lines(item, indent + 4))
            else:
                lines.append(f"{pad}- {_scalar(item)}")
    return lines


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Mapping):
        return "{}"
    if isinstance(value, list):
        return "[]"
    return "'" + str(value).replace("'", "''") + "'"


__all__ = [
    "MOCK_FORWARDED_PORT",
    "MOCK_GUEST_ADDRESS",
    "shipped_output",
    "tenant_account",
    "vm_mock_output",
]
