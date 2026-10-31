"""The ``ssh`` connection kind: how an SSH-based executor reaches a host.

A host with an ``ssh`` connection is reached by connecting to ``ssh_host`` on
``ssh_port`` as ``ssh_user`` with a private key. The key is either ``key_path``,
a file on the provisioning service's own filesystem and not secret, or
``private_key``, key material submitted with the connection, which this codec
protects with the service's Fernet key (scheme ``fernet-v1``) before anything is
stored, and decrypts only to materialize the connection for one execution.
``public_host`` and ``public_port`` are the address and port tenants use to reach
what the host delivers when they reach it on a different route than the
provisioner does; each, when absent, is the connection's own.

The kind is served at version 2 alone, the version that carries
``public_port``. A connection at any other version, submitted or stored, is
refused rather than read under version 2's fields: version 1 has no
``public_port``, and a host stored at version 1 runs again once it is
re-registered at version 2, which keeps its protected key.

The codec is SSH's, not Ansible's: an executor consumes the materialized
connection and holds no cryptography of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compute_provisioning.hosts import ConnectionEnvelope, ProtectedValue
from compute_provisioning_contracts import ConnectionSubmission
from market_config import decrypt_secret, encrypt_secret
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SSH_CONNECTION_KIND = "ssh"
SSH_CONNECTION_VERSION = 2
FERNET_SCHEME = "fernet-v1"
PRIVATE_KEY = "private_key"


class SshConnection(BaseModel):
    """An ``ssh`` connection's public fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The address the provisioner connects to. Required; nothing falls back.
    ssh_host: str = Field(min_length=1)
    #: The address tenants reach the host on; absent, it is ``ssh_host``.
    public_host: str | None = None
    #: The port the provisioner connects to; absent, 22.
    ssh_port: int = Field(default=22, ge=1, le=65535)
    #: The port tenants reach the host on; absent, it is ``ssh_port``.
    public_port: int | None = Field(default=None, ge=1, le=65535)
    #: The account the provisioner connects as; absent, ``root``.
    ssh_user: str = Field(default="root", min_length=1)
    #: The key file on the service's filesystem; absent, the connection's
    #: protected ``private_key`` names the key instead.
    key_path: str | None = None

    def public_fields(self) -> dict[str, Any]:
        """The fields an envelope stores; a connection stating no
        ``public_port`` is stored without the key, never with a null."""
        fields = self.model_dump()
        if fields["public_port"] is None:
            del fields["public_port"]
        return fields

    @field_validator("ssh_host", "ssh_user")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SshConnectionCodec:
    """The ``ssh`` kind's codec, registered with the host authority.

    ``encryption_key`` is the service's Fernet key; it is needed only to protect
    a submitted private key, so a codec without one refuses such a submission
    rather than storing it any other way.
    """

    kind = SSH_CONNECTION_KIND
    version = SSH_CONNECTION_VERSION

    def __init__(self, encryption_key: str | None = None) -> None:
        self._encryption_key = encryption_key

    def build(
        self,
        public: Mapping[str, Any],
        secrets: Mapping[str, str],
        *,
        previous: ConnectionEnvelope | None = None,
    ) -> ConnectionEnvelope:
        unknown = sorted(set(secrets) - {PRIVATE_KEY})
        if unknown:
            raise ValueError(f"invalid ssh connection: unknown secrets {unknown}")
        connection = self._public(public)
        protected: dict[str, ProtectedValue] = {}
        if PRIVATE_KEY in secrets:
            material = secrets[PRIVATE_KEY]
            if not material or not material.strip():
                raise ValueError("invalid ssh connection: private_key is empty")
            if not self._encryption_key:
                raise ValueError(
                    "invalid ssh connection: no key is configured to protect a "
                    "submitted private_key"
                )
            protected[PRIVATE_KEY] = ProtectedValue(
                scheme=FERNET_SCHEME,
                ciphertext=encrypt_secret(material, self._encryption_key),
            )
        elif connection.key_path is None and previous is not None:
            # The previous connection may be stored at a version this codec no
            # longer serves: its protected key is carried as the opaque value it
            # is, never read or decrypted, which is what lets an older host be
            # re-registered at this version without resubmitting its key.
            kept = previous.protected.get(PRIVATE_KEY)
            if kept is not None:
                protected[PRIVATE_KEY] = kept
        return self.validate(
            ConnectionEnvelope(
                kind=self.kind,
                version=self.version,
                public=connection.public_fields(),
                protected=protected,
            )
        )

    def validate(self, envelope: ConnectionEnvelope) -> ConnectionEnvelope:
        if envelope.kind != self.kind or envelope.version != self.version:
            raise ValueError(
                f"not an ssh connection at version {self.version}: "
                f"{envelope.kind!r} at {envelope.version}"
            )
        connection = self._public(envelope.public)
        unknown = sorted(set(envelope.protected) - {PRIVATE_KEY})
        if unknown:
            raise ValueError(f"invalid ssh connection: unknown protected values {unknown}")
        private_key = envelope.protected.get(PRIVATE_KEY)
        if private_key is not None and private_key.scheme != FERNET_SCHEME:
            raise ValueError(
                f"invalid ssh connection: private_key scheme {private_key.scheme!r} "
                f"is not {FERNET_SCHEME!r}"
            )
        if (connection.key_path is None) == (private_key is None):
            raise ValueError(
                "invalid ssh connection: exactly one of key_path and private_key "
                "names the key"
            )
        return ConnectionEnvelope(
            kind=self.kind,
            version=self.version,
            public=connection.public_fields(),
            protected=dict(envelope.protected),
        )

    def decrypt_private_key(self, ciphertext: str) -> str:
        """A protected ``private_key``'s material, for one execution only.

        Raises ``ValueError`` when no key is configured, and
        ``cryptography.fernet.InvalidToken`` when the ciphertext was not
        protected with this codec's key.
        """
        return decrypt_secret(ciphertext, self._encryption_key or "")

    @staticmethod
    def parse(envelope: ConnectionEnvelope) -> SshConnection:
        """The typed public fields an executor reads from a stored envelope.

        The kind and version are checked before any field, so a host stored at
        another version is refused before any playbook runs rather than read
        under this version's fields.
        """
        if envelope.kind != SSH_CONNECTION_KIND or envelope.version != SSH_CONNECTION_VERSION:
            raise ValueError(
                f"not an ssh connection at version {SSH_CONNECTION_VERSION}: "
                f"{envelope.kind!r} at {envelope.version}; re-register the host "
                f"at version {SSH_CONNECTION_VERSION}"
            )
        return SshConnectionCodec._public(envelope.public)

    @staticmethod
    def _public(public: Mapping[str, Any]) -> SshConnection:
        try:
            return SshConnection.model_validate(dict(public))
        except ValidationError as exc:
            raise ValueError(f"invalid ssh connection: {exc}") from exc


def ssh_connection(
    *,
    ssh_host: str,
    ssh_user: str = "root",
    ssh_port: int = 22,
    public_host: str | None = None,
    public_port: int | None = None,
    key_path: str | None = None,
    private_key: str | None = None,
) -> ConnectionSubmission:
    """An ``ssh`` connection as an operator submits it, at the version served.

    Raises ``ValueError`` for a malformed public field, so a typed caller cannot
    send one.
    """
    public = SshConnection(
        ssh_host=ssh_host,
        ssh_user=ssh_user,
        ssh_port=ssh_port,
        public_host=public_host,
        public_port=public_port,
        key_path=key_path,
    ).public_fields()
    secrets = {PRIVATE_KEY: private_key} if private_key is not None else {}
    return ConnectionSubmission(
        kind=SSH_CONNECTION_KIND,
        version=SSH_CONNECTION_VERSION,
        public=public,
        secrets=secrets,
    )


__all__ = [
    "FERNET_SCHEME",
    "PRIVATE_KEY",
    "SSH_CONNECTION_KIND",
    "SSH_CONNECTION_VERSION",
    "SshConnection",
    "SshConnectionCodec",
    "ssh_connection",
]
