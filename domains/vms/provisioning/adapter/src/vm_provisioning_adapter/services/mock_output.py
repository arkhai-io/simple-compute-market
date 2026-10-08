"""The output a VM job produces under the mock profile when no rule replaces it.

The mock Ansible runner renders a run's output with the function a domain
contributes; this is VM's. It is what the VM-operations playbook prints for a
create, credentials included, so the VM codec reads the same fields from it
that it reads from a real run.
"""

from __future__ import annotations

from compute_provisioning_ansible import MockPlaybook

MOCK_VM_CREATE_STDOUT = """\
PLAY [Mock Provision] *********************************************************

TASK [debug] ******************************************************************
ok: [kvm1] => {
    "vm_creation_data": {
        "action": "create",
        "vm_name": "mock-vm",
        "status": "running",
        "host": "kvm1",
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


def vm_mock_output(playbook: MockPlaybook) -> str:
    """A successful create, whatever the job."""
    return MOCK_VM_CREATE_STDOUT


__all__ = ["MOCK_VM_CREATE_STDOUT", "vm_mock_output"]
