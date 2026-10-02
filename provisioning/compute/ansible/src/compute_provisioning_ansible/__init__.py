"""The compute family kit's Ansible implementation distribution.

It implements execution for the compute family over Ansible and SSH: the
``ssh`` connection codec and Ansible inventories as an input format. It
depends on ``compute_provisioning``; nothing in ``compute_provisioning``
depends on it.
"""

from .connection import (
    FERNET_SCHEME,
    PRIVATE_KEY,
    SSH_CONNECTION_KIND,
    SSH_CONNECTION_VERSION,
    SshConnection,
    SshConnectionCodec,
    ssh_connection,
)
from .inventory import DEFAULT_KEY_PATH, parse_inventory_ini

__all__ = [
    "DEFAULT_KEY_PATH",
    "FERNET_SCHEME",
    "PRIVATE_KEY",
    "SSH_CONNECTION_KIND",
    "SSH_CONNECTION_VERSION",
    "SshConnection",
    "SshConnectionCodec",
    "parse_inventory_ini",
    "ssh_connection",
]
