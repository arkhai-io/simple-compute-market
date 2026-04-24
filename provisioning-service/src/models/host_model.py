"""Pydantic models for the host registry API.

HostCreate / HostUpdate are request bodies.
HostResponse is the serialized view returned to callers (never exposes
ssh_key_value — callers have no need to read back raw key material).
HostListResponse wraps a list of HostResponse for GET /hosts/.
HostImportRequest carries a raw Ansible INI block for POST /hosts/import.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class HostCreate(BaseModel):
    """Body accepted by ``POST /api/v1/hosts/``."""

    name: str = Field(description="Ansible alias / hostname key (e.g. 'ww1').")
    kvm_host: str = Field(description="IP address or hostname for SSH.")
    ssh_user: str = Field(description="SSH login user on the KVM host.")
    ssh_key_type: Literal["path", "embedded"] = Field(
        default="path",
        description=(
            "'path' — ssh_key_value is a filesystem path to the private key. "
            "'embedded' — ssh_key_value is raw PEM key material; stored "
            "Fernet-encrypted using SSH_DECRYPTION_KEY."
        ),
    )
    ssh_key_value: str = Field(
        description=(
            "For 'path': absolute filesystem path to the private key file "
            "(e.g. '/home/appuser/.ssh/id_ed25519'). "
            "For 'embedded': raw unencrypted PEM private key content."
        )
    )
    gpu_count: int = Field(default=0, ge=0, description="Number of GPUs on this host.")
    enabled: bool = Field(default=True, description="Whether the host is active.")


class HostUpdate(BaseModel):
    """Body accepted by ``PUT /api/v1/hosts/{host}``.

    All fields are optional; only supplied fields are updated.
    """

    kvm_host: Optional[str] = None
    ssh_user: Optional[str] = None
    ssh_key_type: Optional[Literal["path", "embedded"]] = None
    ssh_key_value: Optional[str] = None
    gpu_count: Optional[int] = Field(default=None, ge=0)


class HostResponse(BaseModel):
    """Serialized host returned by all host endpoints.

    ``ssh_key_value`` is intentionally absent — raw or encrypted key
    material is never returned over the API.
    """

    name: str
    kvm_host: str
    ssh_user: str
    ssh_key_type: str
    gpu_count: int
    enabled: bool

    model_config = {"from_attributes": True}


class HostListResponse(BaseModel):
    """Response body for ``GET /api/v1/hosts/``."""

    hosts: list[HostResponse]


class HostImportRequest(BaseModel):
    """Body accepted by ``POST /api/v1/hosts/import``.

    ``ini_content`` must be a valid Ansible INI inventory block.
    Hosts are upserted (append-only); existing hosts not present in the
    INI are left untouched.

    Example::

        [kvm_hosts]
        ww1  ansible_host=10.0.0.1  ansible_user=ubuntu  ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519
        ww2  ansible_host=10.0.0.2  ansible_user=ubuntu  ansible_ssh_private_key_file=/home/appuser/.ssh/id_ed25519
    """

    ini_content: str = Field(description="Ansible INI inventory block.")
    ssh_key_type: Literal["path", "embedded"] = Field(
        default="path",
        description=(
            "Key type applied to all hosts imported from this INI. "
            "For 'path', ansible_ssh_private_key_file is stored as-is. "
            "For 'embedded', it is treated as a path to read and embed."
        ),
    )
