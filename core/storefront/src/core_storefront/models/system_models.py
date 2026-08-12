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
    # Whether timer-driven loops are held idle. Distinct from `paused`, which is
    # about accepting new negotiations: a storefront may trade with its loops idle
    # or run its loops while closed for business.
    loops_paused: bool | None = None
    # Per timer loop: "running", "stopped", "cancelled", or "exited". Reported
    # beside `paused` because the flag and the loops can disagree — a loop that
    # exited on its own is neither running nor deliberately halted, and a single
    # boolean would report that as healthy.
    loops: dict[str, str] | None = None
    agent_id: str | None = None
    chain_id: int | None = None
    resource_count: int | None = None
    site_projections: dict[str, dict[str, ProjectionFamilyStatus]] | None = None
    # Per-site, per-pool operator-visible reason a projected `listing_mode`
    # fell back to a domain's structural default (unrecognized raw value).
    # A pool's absence means no fallback is owed, not that data is missing.
    listing_mode_explanations: dict[str, dict[str, str]] | None = None


class AdminPauseResponse(BaseModel):
    """Response for POST /api/v1/admin/pause and /resume.

    `loops` reports each timer loop's state after the call. Pause halts them as
    well as refusing new negotiations, so a bare `paused` boolean would say the
    flag was set without saying whether the background work actually stopped —
    which is the substantive half of what pause now means.
    """

    paused: bool
    message: str = ""
    loops: dict[str, str] = Field(default_factory=dict)


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int
