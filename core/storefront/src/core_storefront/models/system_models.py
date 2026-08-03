"""Schema-invariant storefront system/admin response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class AdminPauseResponse(BaseModel):
    paused: bool
    message: str = ""


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int
