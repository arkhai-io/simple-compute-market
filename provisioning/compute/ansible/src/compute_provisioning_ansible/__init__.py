"""The compute family kit's Ansible implementation distribution.

It implements execution for the compute family over Ansible and SSH, and
depends on ``compute_provisioning``; nothing in ``compute_provisioning``
depends on it.
"""

from .connection import (
    SSH_CONNECTION_KIND,
    SSH_CONNECTION_VERSION,
    SshConnection,
    SshConnectionCodec,
)

__all__ = [
    "SSH_CONNECTION_KIND",
    "SSH_CONNECTION_VERSION",
    "SshConnection",
    "SshConnectionCodec",
]
