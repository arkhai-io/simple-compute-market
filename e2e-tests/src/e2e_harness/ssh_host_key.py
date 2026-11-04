"""Validate an operator-pinned SSH host public key without accepting key options."""
from __future__ import annotations

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, load_ssh_public_key,
)


def canonical_host_public_key(value: str) -> str:
    """Return the algorithm and key blob; comments carry no trust authority."""
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        raise ValueError("ssh_host_public_key must be one OpenSSH public key line")
    try:
        key = load_ssh_public_key(value.encode("utf-8"))
    except (ValueError, TypeError, UnicodeError, UnsupportedAlgorithm):
        raise ValueError("ssh_host_public_key must be a valid OpenSSH public key") from None
    return key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode("ascii")
