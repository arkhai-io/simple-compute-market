"""Wire models for relay administration.

Shared by the provisioning service's relay controller and the canonical client,
so the two cannot drift. A test that hand-builds a request body proves the
server accepts that body; it proves nothing about the body the production
client actually sends, and the two can diverge while the test stays green.

No model here carries an admission token on a read. ``token_configured``
answers the question an operator has — is this relay usable — without
disclosing the value, and a field that is never returned cannot be exposed by a
serializer someone adds later.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "RelayCreate",
    "RelayListResponse",
    "RelayResponse",
    "RelayTokenRotate",
    "RelayUpdate",
]


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
