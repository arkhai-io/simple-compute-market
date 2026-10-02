"""The ``ssh`` connection kind: how an Ansible executor reaches a host.

A host registered with an ``ssh`` connection is reached by connecting to
``ssh_host`` on ``ssh_port`` as ``ssh_user`` with a private key. The key is
either a path on the provisioning service's own filesystem (``path``), which is
not secret, or the key material itself (``embedded``), which is.
``public_host`` is the address tenants use to reach what the host delivers when
they reach it on a different network than the provisioner does.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SSH_CONNECTION_KIND = "ssh"
SSH_CONNECTION_VERSION = 1


class SshConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ssh_host: str = Field(min_length=1)
    public_host: str | None = None
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root", min_length=1)
    ssh_key_type: Literal["path", "embedded"] = "path"
    ssh_key_value: str = Field(min_length=1)

    @field_validator("ssh_host", "ssh_user", "ssh_key_value")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SshConnectionCodec:
    """The ``ssh`` kind's codec, registered with the host authority."""

    kind = SSH_CONNECTION_KIND
    version = SSH_CONNECTION_VERSION

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return SshConnection.model_validate(dict(payload)).model_dump()
        except ValidationError as exc:
            raise ValueError(f"invalid ssh connection: {exc}") from exc

    def secret_fields(self, payload: Mapping[str, Any]) -> frozenset[str]:
        if payload.get("ssh_key_type") == "embedded":
            return frozenset({"ssh_key_value"})
        return frozenset()

    def parse(self, payload: Mapping[str, Any]) -> SshConnection:
        """The typed connection an executor reads, from a validated payload."""
        return SshConnection.model_validate(dict(payload))


__all__ = [
    "SSH_CONNECTION_KIND",
    "SSH_CONNECTION_VERSION",
    "SshConnection",
    "SshConnectionCodec",
]
