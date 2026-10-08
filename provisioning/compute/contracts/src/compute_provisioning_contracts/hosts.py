"""Wire models of the host registry's operator routes.

A host is the machine a provisioning executor runs jobs against, identified by
``host_id``, with a connection whose kind names the codec that understands it.
A request submits a connection's public fields and any secrets; a secret is
write-only: it is protected by the kind's codec before it is stored, and a
response names each protected value and its scheme, never its content. The site
authority references a host only by ``host_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConnectionSubmission(BaseModel):
    """A connection as an operator submits it."""

    kind: str = Field(min_length=1, description="The connection kind, e.g. 'ssh'.")
    version: int = Field(default=1, ge=1, description="The kind's payload version.")
    public: dict[str, Any] = Field(
        default_factory=dict, description="The kind's non-secret fields."
    )
    secrets: dict[str, str] = Field(
        default_factory=dict,
        repr=False,
        description=(
            "Secret material the kind takes, protected before storage and never "
            "returned. Omitted on an update, a stored secret the connection still "
            "needs is kept."
        ),
    )


class ConnectionView(BaseModel):
    """A stored connection as a read returns it: protected values by scheme only."""

    kind: str
    version: int
    public: dict[str, Any]
    protected: dict[str, str] = Field(
        default_factory=dict,
        description="Each protected value's name and the scheme protecting it.",
    )


class HostCreate(BaseModel):
    """Body accepted by ``POST /api/v1/hosts/``."""

    host_id: str = Field(description="The host's identity, e.g. 'kvm1' or 'bm-node-1'.")
    connection: ConnectionSubmission
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

    connection: Optional[ConnectionSubmission] = Field(
        default=None, description="A replacement connection."
    )
    gpu_count: Optional[int] = Field(default=None, ge=0)
    gpu_model: Optional[str] = Field(default=None, description="Updated descriptive GPU model.")
    enabled: Optional[bool] = Field(default=None)
    pool_id: Optional[str] = Field(default=None, description="Reassign this host to a different pool.")


class HostResponse(BaseModel):
    """A registered host as every host endpoint returns it."""

    host_id: str
    connection: ConnectionView
    gpu_count: int
    gpu_model: Optional[str] = None
    enabled: bool
    pool_id: str
    created_at: datetime
    updated_at: datetime


class HostListResponse(BaseModel):
    """Response body for ``GET /api/v1/hosts/``."""

    hosts: list[HostResponse]
    total: int


class ConnectivityResult(BaseModel):
    """Whether a host's connection could be reached and authenticated."""

    host: str = Field(description="The host that was tested.")
    reachable: bool = Field(
        description="True if the host's connection authenticated and ran a command."
    )
    detail: str = Field(
        description="The probe's output on success, or its error on failure."
    )


__all__ = [
    "ConnectivityResult",
    "ConnectionSubmission",
    "ConnectionView",
    "HostCreate",
    "HostListResponse",
    "HostResponse",
    "HostUpdate",
]
