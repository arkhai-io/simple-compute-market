"""Schema-invariant storefront system/admin response models."""

from __future__ import annotations

from typing import Any, Literal

from market_identity import Identity
from pydantic import BaseModel, ConfigDict, Field


class ProjectionFamilyStatus(BaseModel):
    """One projection family's (resource-pool or capacity-bucket) load
    state for one configured site, as reported on the operator status
    surface. Absence of a site, or a `not_loaded`/`unavailable`/`invalid`
    state, means the projection has not yet been confirmed -- never
    authoritative empty capacity.

    fetched_at:
        ISO8601 UTC timestamp of the last time this generation was
        *confirmed* current -- includes an unchanged-identity poll
        confirmation, not only a full snapshot transfer. See
        `core_storefront.site_projections.ProjectionCacheView`.
    """

    state: str
    revision: int | None = None
    digest: str | None = None
    last_error: str | None = None
    fetched_at: str | None = None


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    paused: bool | None = None
    agent_id: str | None = None
    chain_id: int | None = None
    resource_count: int | None = None
    site_projections: dict[str, dict[str, ProjectionFamilyStatus]] | None = None
    # Per-site, per-pool operator-visible reason a projected `listing_mode`
    # fell back to a domain's structural default (unrecognized raw value).
    # A pool's absence means no fallback is owed, not that data is missing.
    listing_mode_explanations: dict[str, dict[str, str]] | None = None


class AdminPauseResponse(BaseModel):
    paused: bool
    message: str = ""


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int



class IdentityRetirementRequest(BaseModel):
    """Complete one already-applied two-proof identity rotation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    authority: str = Field(min_length=1, max_length=256)
    subject: str = Field(min_length=1, max_length=256)
    rotation_nonce: str = Field(min_length=1, max_length=128)
    principal: Identity


class IdentityBindingResponse(BaseModel):
    """One durable principal binding at the instant status was observed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    principal: Identity
    status: Literal["primary", "overlap", "retired", "disabled"]
    overlap_until: int | None
    active: bool


class IdentityStatusResponse(BaseModel):
    """Operator-visible identity authority state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    authority: str
    subject: str
    role: str
    bindings: tuple[IdentityBindingResponse, ...]
    primary: Identity
    observed_at: int