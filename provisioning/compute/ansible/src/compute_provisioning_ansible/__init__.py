"""The compute family kit's Ansible implementation distribution.

It implements execution for the compute family over Ansible and SSH: the
``ssh`` connection codec, Ansible inventories as an input format, the runner,
and ``AnsibleJobExecutor``, which runs any domain's jobs through the
``AnsibleJobCodec`` that domain contributes. It depends on
``compute_provisioning``; nothing in ``compute_provisioning`` depends on it.
"""

from pathlib import Path

from .codec import (
    AnsibleJobCodec,
    AnsibleJobInterpretation,
    AnsibleJobPlan,
    matches_any,
    render_extra_vars,
    write_extra_vars,
)
from .connection import (
    FERNET_SCHEME,
    PRIVATE_KEY,
    SSH_CONNECTION_KIND,
    SSH_CONNECTION_VERSION,
    SshConnection,
    SshConnectionCodec,
    ssh_connection,
)
from .executor import TRANSPORT_FAILURES, AnsibleJobExecutor
from .inventory import DEFAULT_KEY_PATH, parse_inventory_ini
from .mock import DefaultOutput, MockAnsibleRunner, MockPlaybook
from .probes import (
    AnsibleReadinessResponse,
    FileInfo,
    InventoryInfo,
    SshKeyInfo,
    ansible_readiness,
    probe_connectivity,
)
from .runner import ConnectivityResult

#: The Ansible configuration every playbook the service runs is run under,
#: exported as ``ANSIBLE_CONFIG`` unless a deployment names its own.
DEFAULT_ANSIBLE_CONFIG = Path(__file__).with_name("ansible.cfg")

__all__ = [
    "DEFAULT_ANSIBLE_CONFIG",
    "AnsibleJobCodec",
    "AnsibleReadinessResponse",
    "ConnectivityResult",
    "DefaultOutput",
    "FileInfo",
    "InventoryInfo",
    "MockAnsibleRunner",
    "MockPlaybook",
    "SshKeyInfo",
    "ansible_readiness",
    "probe_connectivity",
    "AnsibleJobExecutor",
    "AnsibleJobInterpretation",
    "AnsibleJobPlan",
    "DEFAULT_KEY_PATH",
    "FERNET_SCHEME",
    "PRIVATE_KEY",
    "SSH_CONNECTION_KIND",
    "SSH_CONNECTION_VERSION",
    "SshConnection",
    "SshConnectionCodec",
    "TRANSPORT_FAILURES",
    "matches_any",
    "parse_inventory_ini",
    "render_extra_vars",
    "ssh_connection",
    "write_extra_vars",
]
