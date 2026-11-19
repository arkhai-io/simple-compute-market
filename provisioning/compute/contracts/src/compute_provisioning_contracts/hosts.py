"""Wire models of the host registry's operator routes.

A host is the machine a provisioning executor runs jobs against, identified by
``host_id``, with a connection whose kind names the codec that understands it.
A request submits a connection's public fields and any secrets; a secret is
write-only: it is protected by the kind's codec before it is stored, and a
response names each protected value and its scheme, never its content. The site
authority references a host only by ``host_id``.

A host describes no hardware: what a machine has, and sells, is stated only by
its capacity declaration. The request models ignore any field they do not
define, ``gpu_count`` and ``gpu_model`` among them, so a body carrying them is
accepted with them ignored.

A host definitions document declares hosts in bulk, with the same field names:
a top-level ``hosts`` list of ``HostDefinition`` entries. Unlike the request
models, an entry refuses any field it does not define and carries no secret,
since the document is configuration rather than a credential store. A
connection states its ``version`` in both.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConnectionSubmission(BaseModel):
    """A connection as an operator submits it.

    ``version`` is required: a submission's meaning must not depend on a
    default, and the service refuses a version its kind's codec does not serve.
    """

    kind: str = Field(min_length=1, description="The connection kind, e.g. 'ssh'.")
    version: int = Field(ge=1, description="The kind's payload version.")
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
    enabled: bool = Field(default=True, description="Whether this host is available for jobs.")
    pool_id: Optional[str] = Field(
        default=None,
        description=(
            "Resource pool this host is placed in, which must exist. Omitted, the "
            "host is unplaced: it belongs to no pool."
        ),
    )


class HostUpdate(BaseModel):
    """Body accepted by ``PUT /api/v1/hosts/{host_id}``.

    A field the request omits is left as it is. ``pool_id`` alone tells an
    explicit ``null`` from an omitted field: ``null`` unplaces the host.
    """

    connection: Optional[ConnectionSubmission] = Field(
        default=None, description="A replacement connection."
    )
    enabled: Optional[bool] = Field(default=None)
    pool_id: Optional[str] = Field(
        default=None,
        description=(
            "Move this host to another existing pool, or unplace it with an explicit "
            "null. Omitted, the host keeps its pool."
        ),
    )


class HostResponse(BaseModel):
    """A registered host as every host endpoint returns it."""

    host_id: str
    connection: ConnectionView
    enabled: bool
    pool_id: Optional[str] = Field(description="The host's pool, or null when it is unplaced.")
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


class HostDefinitionConnection(BaseModel):
    """A host definitions entry's connection: its public fields and no secret.

    ``version`` is required because a document's meaning must not depend on a
    default; a service refuses a kind or version it does not serve. A key is
    named by its file path among the public fields, never carried: the model
    refuses a ``secrets`` field like any field it does not define, and a
    document's validation reports it under its own code,
    ``HostDefinitionProblemCode.CONNECTION_SECRETS``.

    Validation of the fields this model defines is strict, as for every
    document entry: a quoted number or boolean is the wrong type, not a value
    to coerce. ``public`` holds the kind's own fields, which this model cannot
    type; they are validated by the kind's codec, under that codec's rules.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: str = Field(min_length=1, description="The connection kind, e.g. 'ssh'.")
    version: int = Field(ge=1, description="The kind's payload version.")
    public: dict[str, Any] = Field(
        default_factory=dict, description="The kind's non-secret fields."
    )


class HostDefinition(BaseModel):
    """One entry of a host definitions document: the whole of one host.

    Applied, an entry registers its host or replaces all of its non-secret
    state: an omitted ``pool_id`` (or an explicit null) unplaces it, and an
    omitted ``enabled`` enables it. Validation is strict, so ``enabled: null``
    and a quoted boolean are refused.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    host_id: str = Field(min_length=1)
    pool_id: Optional[str] = Field(default=None, min_length=1)
    enabled: bool = True
    connection: HostDefinitionConnection


class HostDefinitionProblemCode(StrEnum):
    """The codes a host definitions problem carries, one spelling for every party."""

    INVALID_YAML = "invalid_yaml"
    INVALID_TYPE = "invalid_type"
    #: A value of the right type outside its bounds, such as a version below 1.
    INVALID_VALUE = "invalid_value"
    UNKNOWN_FIELD = "unknown_field"
    REQUIRED_FIELD = "required_field"
    DUPLICATE_HOST_ID = "duplicate_host_id"
    #: An entry stating ``connection.secrets``: the document carries no credential.
    CONNECTION_SECRETS = "connection_secrets"
    UNKNOWN_POOL = "unknown_pool"
    #: The connection's kind codec refused it: an unserved kind or version, or a
    #: connection naming no key it can use.
    INVALID_CONNECTION = "invalid_connection"
    #: A host pool-change hook refused the move the entry makes.
    POOL_CHANGE_REFUSED = "pool_change_refused"


class HostDefinitionProblem(BaseModel):
    """One problem found in a host definitions document, at its location.

    ``code`` is one of ``HostDefinitionProblemCode``'s values; it is read as
    text so a reader keeps working when a newer service reports a code it does
    not know.
    """

    path: str
    code: str
    message: str


class HostDefinitionsDiff(BaseModel):
    """The hosts a document creates, updates, and leaves unchanged, by ``host_id``."""

    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)


class HostDefinitionsImportRequest(BaseModel):
    """Body accepted by ``POST /api/v1/hosts/definitions/import``."""

    yaml_text: str = Field(
        description="Host definitions YAML with a top-level 'hosts' list."
    )
    validate_only: bool = Field(
        default=False,
        description="Report the problems and the planned changes without applying either.",
    )


class HostDefinitionsImportResponse(BaseModel):
    """What an import applied or would apply, and every problem it found.

    ``applied`` is true only for an applying request with no problem; a
    document with any problem applies nothing. A structurally invalid document
    is never checked against stored state, so its ``diff`` and ``not_named``
    are empty. For a structurally valid one, ``diff`` holds what its accepted
    entries change, or would change, and ``not_named`` lists the registered
    hosts the document does not name, which it leaves as they are.
    """

    applied: bool
    diff: HostDefinitionsDiff = Field(default_factory=HostDefinitionsDiff)
    not_named: list[str] = Field(default_factory=list)
    problems: list[HostDefinitionProblem] = Field(default_factory=list)


__all__ = [
    "ConnectivityResult",
    "ConnectionSubmission",
    "ConnectionView",
    "HostCreate",
    "HostDefinition",
    "HostDefinitionConnection",
    "HostDefinitionProblem",
    "HostDefinitionProblemCode",
    "HostDefinitionsDiff",
    "HostDefinitionsImportRequest",
    "HostDefinitionsImportResponse",
    "HostListResponse",
    "HostResponse",
    "HostUpdate",
]
