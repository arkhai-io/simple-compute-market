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
    # Per timer loop: "starting", "running", "pausing", "paused", "cancelled",
    # or "exited". Reported beside the flags because they and the loops can
    # disagree — a loop scheduled but not yet cycling cannot observe a pause, and
    # one that exited on its own is neither running nor deliberately halted. A
    # single boolean reports both as healthy.
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
    """Response for the trading and lifecycle pause/resume routes.

    The two controls are independent: `/admin/pause` refuses new negotiations and
    leaves the timer loops running, `/admin/lifecycle/pause` holds the loops idle
    and leaves the storefront open to trade.

    `loops` reports each timer loop's state after the call, and is the
    substantive half of a lifecycle pause: a bare `paused` boolean says the flag
    was set without saying whether the background work actually stopped.
    """

    paused: bool
    message: str = ""
    loops: dict[str, str] = Field(default_factory=dict)


class StageEventResponse(BaseModel):
    """Response for GET /api/v1/system/events (non-streaming).

    `truncated` is not derivable from `count`: a caller that receives exactly the
    page cap cannot otherwise tell a complete result from a partial one, and one
    reasoning about a whole history would silently reason about part of one.
    """

    events: list[dict[str, Any]]
    count: int
    truncated: bool = False
