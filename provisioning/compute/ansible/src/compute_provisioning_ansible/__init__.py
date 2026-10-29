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
    SSH_CONNECTION_VERSIONS,
    SSH_PUBLIC_PORT_VERSION,
    SshConnection,
    SshConnectionCodec,
    SshConnectionV1,
    ssh_connection,
    ssh_connection_codecs,
)
from .executor import TRANSPORT_FAILURES, AnsibleJobExecutor
from .inventory import DEFAULT_KEY_PATH, parse_inventory_ini
from .mock import DefaultOutput, MockAnsibleRunner, MockPlaybook
from .probes import probe_connectivity
from .readiness import (
    ANSIBLE_COMPONENT,
    AnsibleReadinessDetail,
    FileInfo,
    SshKeyInfo,
    ansible_readiness_component,
)
from .runner import read_fact

#: The Ansible configuration every playbook the service runs is run under,
#: exported as ``ANSIBLE_CONFIG`` unless a deployment names its own.
DEFAULT_ANSIBLE_CONFIG = Path(__file__).with_name("ansible.cfg")

__all__ = [
    "DEFAULT_ANSIBLE_CONFIG",
    "AnsibleJobCodec",
    "ANSIBLE_COMPONENT",
    "AnsibleReadinessDetail",
    "DefaultOutput",
    "FileInfo",
    "MockAnsibleRunner",
    "MockPlaybook",
    "SshKeyInfo",
    "ansible_readiness_component",
    "probe_connectivity",
    "AnsibleJobExecutor",
    "AnsibleJobInterpretation",
    "AnsibleJobPlan",
    "DEFAULT_KEY_PATH",
    "FERNET_SCHEME",
    "PRIVATE_KEY",
    "SSH_CONNECTION_KIND",
    "SSH_CONNECTION_VERSION",
    "SSH_CONNECTION_VERSIONS",
    "SSH_PUBLIC_PORT_VERSION",
    "SshConnection",
    "SshConnectionCodec",
    "SshConnectionV1",
    "TRANSPORT_FAILURES",
    "matches_any",
    "parse_inventory_ini",
    "read_fact",
    "render_extra_vars",
    "ssh_connection",
    "ssh_connection_codecs",
    "write_extra_vars",
]
