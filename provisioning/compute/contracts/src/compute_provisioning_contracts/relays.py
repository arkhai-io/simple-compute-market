"""Wire models for relay administration.

Shared by the provisioning service's relay routes and the family's typed
clients, so the two cannot drift. A test that hand-builds a request body proves
the server accepts that body; it proves nothing about the body the production
client actually sends, and the two can diverge while the test stays green.

No model here carries an admission token or a private key on a read.
``token_configured`` answers the question an operator has — is this relay
usable — without disclosing the value, a grant key is shown only by its id and
public half, and a field that is never returned cannot be exposed by a
serializer someone adds later.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr

__all__ = [
    "RelayActiveGrantKey",
    "RelayCreate",
    "RelayGrantKeyStage",
    "RelayGrantKeys",
    "RelayLeaseListResponse",
    "RelayLeaseView",
    "RelayListResponse",
    "RelayResponse",
    "RelayRetiredGrantKey",
    "RelayStagedGrantKey",
    "RelayTokenRotate",
    "RelayUpdate",
]


class RelayActiveGrantKey(BaseModel):
    """The relay's active grant-signing key.

    ``kid`` is the key's RFC 7638 thumbprint, the id the admission plugin
    derives; ``public_key`` is the standard base64 of its DER
    SubjectPublicKeyInfo, the form the plugin's configuration takes.
    """

    kid: str
    public_key: str
    activated_at: datetime


class RelayStagedGrantKey(BaseModel):
    """A key staged for rotation, not active until it is activated."""

    kid: str
    public_key: str


class RelayRetiredGrantKey(BaseModel):
    """A key the relay held before its active one.

    ``grants_valid_until`` is when the last grant it may have signed for an
    unreleased lease expires; None once no such lease remains, when the key
    can be removed from the relay's plugin.
    """

    kid: str
    retired_at: datetime
    grants_valid_until: datetime | None = None


class RelayGrantKeys(BaseModel):
    active: RelayActiveGrantKey | None = None
    staged: RelayStagedGrantKey | None = None
    retired: list[RelayRetiredGrantKey] = Field(default_factory=list)


class RelayResponse(BaseModel):
    """A relay as callers see it."""

    id: str
    label: str | None = None
    relay_addr: str
    relay_port: int
    vm_port_range_start: int
    vm_port_range_count: int
    enabled: bool
    token_configured: bool
    grant_keys: RelayGrantKeys


class RelayListResponse(BaseModel):
    relays: list[RelayResponse]


class RelayCreate(BaseModel):
    relay_addr: str
    relay_port: int
    vm_port_range_start: int
    vm_port_range_count: int
    id: str | None = None
    label: str | None = None
    token: str | None = None
    enabled: bool = True


class RelayUpdate(BaseModel):
    """Partial update. An omitted field is unchanged.

    No token field. Rotation is its own operation: it is the one write whose
    effect is invisible in every subsequent read, so it should be requested
    deliberately rather than carried along by an edit to a label, and it should
    be distinguishable in an audit trail from one.
    """

    label: str | None = None
    relay_addr: str | None = None
    relay_port: int | None = None
    vm_port_range_start: int | None = None
    vm_port_range_count: int | None = None


class RelayTokenRotate(BaseModel):
    token: str = Field(min_length=1)


class RelayGrantKeyStage(BaseModel):
    """Stage a relay's next grant key: the one supplied, or one the service makes.

    ``private_key`` is the single-line standard base64 of an Ed25519 key's
    PKCS#8 DER. It is held as a secret value, so neither its ``repr`` nor a
    serialization of the model shows it; the typed client sends the value
    itself. An unknown field is refused rather than ignored: a misspelled
    ``private_key`` would otherwise stage a generated key in place of the one
    the operator keeps in the secrets profile.
    """

    model_config = ConfigDict(extra="forbid")

    private_key: SecretStr | None = None


class RelayLeaseView(BaseModel):
    """One port a relay holds or held: what it is bound for, and whether it
    has been released. Carries no credential."""

    lease_id: str
    remote_port: int
    host_id: str | None = None
    pool_id: str | None = None
    # The reservation whose released capacity releases the lease, under the
    # kind of owner that holds it.
    owner_kind: str
    owner_id: str
    allocated_at: datetime
    released_at: datetime | None = None
    # When this tenancy's grants expire, fixed when the port was leased, and
    # the id of the key that signed its latest grant, None until one is.
    grant_expires_at: datetime | None = None
    grant_key_id: str | None = None


class RelayLeaseListResponse(BaseModel):
    """A relay's holdings, every lease row it has, by remote port.

    A released row stays until its port is leased again, so a released
    delivery's port reads released until then.
    """

    relay_id: str
    leases: list[RelayLeaseView]
