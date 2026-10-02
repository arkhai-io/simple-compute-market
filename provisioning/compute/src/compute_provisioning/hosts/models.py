"""Wire models of the host registry's operator routes.

A host is the machine a provisioning executor connects to, identified by
``host_id``, with its connection information and protected connection material.
The site authority references a host only by ``host_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class HostCreate(BaseModel):
    """Body accepted by ``POST /api/v1/hosts/``."""

    host_id: str = Field(description="The host's identity, e.g. 'kvm1' or 'bm-node-1'.")
    ssh_host: str = Field(description="IP/hostname the provisioner SSHes to.")
    public_host: Optional[str] = Field(
        default=None,
        description=(
            "Address tenants use to reach what this host delivers "
            "(public IP, DNS, or overlay IP). Defaults to ssh_host when "
            "omitted — set it when buyers reach the host on a different "
            "network than the provisioner does."
        ),
    )
    ssh_user: str = Field(default="root", description="SSH user the provisioner connects as.")
    ssh_port: int = Field(
        default=22,
        ge=1,
        le=65535,
        description=(
            "Port the provisioner connects to. Set it when the host answers "
            "SSH somewhere other than port 22 at ssh_host — through a reverse "
            "tunnel, a NAT forward, or a bastion."
        ),
    )
    ssh_key_type: Literal["path", "embedded"] = Field(
        default="path",
        description=(
            "'path' stores a filesystem path to the SSH key; "
            "'embedded' stores Fernet-encrypted key material in the database."
        ),
    )
    ssh_key_value: str = Field(
        description=(
            "For 'path': absolute path to the SSH private key on the service host. "
            "For 'embedded': Fernet-encrypted PEM key material."
        )
    )
    gpu_count: int = Field(default=0, ge=0, description="Number of GPU cards on the host.")
    gpu_model: Optional[str] = Field(
        default=None, description="Descriptive GPU model, e.g. 'H100', 'A100'.",
    )
    enabled: bool = Field(default=True, description="Whether this host is available for jobs.")
    pool_id: Optional[str] = Field(
        default=None,
        description="Resource pool this host belongs to. Defaults to the 'default' pool.",
    )


class HostUpdate(BaseModel):
    """Body accepted by ``PUT /api/v1/hosts/{host_id}``."""

    ssh_host: Optional[str] = Field(default=None, description="Updated IP/hostname.")
    public_host: Optional[str] = Field(default=None, description="Updated public address.")
    ssh_user: Optional[str] = Field(default=None, description="Updated SSH user.")
    ssh_port: Optional[int] = Field(
        default=None, ge=1, le=65535, description="Updated SSH port.",
    )
    ssh_key_type: Optional[Literal["path", "embedded"]] = Field(default=None)
    ssh_key_value: Optional[str] = Field(default=None, description="Updated key path or material.")
    gpu_count: Optional[int] = Field(default=None, ge=0)
    gpu_model: Optional[str] = Field(default=None, description="Updated descriptive GPU model.")
    enabled: Optional[bool] = Field(default=None)
    pool_id: Optional[str] = Field(default=None, description="Reassign this host to a different pool.")


class HostResponse(BaseModel):
    """Serialised host row returned by all host endpoints.

    ``ssh_key_value`` is intentionally absent — callers have no need to
    read back raw or encrypted key material.
    """

    host_id: str
    ssh_host: str
    public_host: Optional[str] = None
    ssh_user: str
    ssh_port: int
    ssh_key_type: str
    gpu_count: int
    gpu_model: Optional[str] = None
    enabled: bool
    pool_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HostListResponse(BaseModel):
    """Response body for ``GET /api/v1/hosts/``."""

    hosts: list[HostResponse]
    total: int


__all__ = ["HostCreate", "HostListResponse", "HostResponse", "HostUpdate"]
