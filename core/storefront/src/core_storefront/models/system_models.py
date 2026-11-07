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


class LoopCycleError(BaseModel):
    """The error that ended a loop's cycle, as status may show it.

    `message` is present only for an error the storefront declared
    disclosable -- its own configuration and publication errors, whose text
    names keys and reasons. Any other error is reported by its type alone, so
    no credential, secret, or private URL reaches status.
    """

    type: str
    message: str | None = None


class LoopCycleOutcome(BaseModel):
    """The terminal outcome of one loop cycle, whether its timer or an
    operator's step ran it (`trigger`). A failed cycle names the stage it
    failed in -- `compose`, `run`, or `converge` -- unless it was cancelled
    before any stage began."""

    finished_at: str
    trigger: str
    completed: bool
    stage: str | None = None
    error: LoopCycleError | None = None


class LoopStatus(BaseModel):
    """One lifecycle loop as the storefront's loop controller reports it.

    `state` is the controller's: `starting`, `running`, `pausing`, `paused`,
    `exited`, or `cancelled`; it is `None` for a loop whose timer is not
    running, such as one an operator only steps. It is independent of
    `last_outcome`: a running loop whose last cycle failed is still running,
    and an exited loop runs no further cycles whatever its last outcome was.
    """

    name: str
    state: str | None = None
    last_outcome: LoopCycleOutcome | None = None


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    paused: bool | None = None
    agent_id: str | None = None
    chain_id: int | None = None
    site_projections: dict[str, dict[str, ProjectionFamilyStatus]] | None = None
    # Per-site, per-pool operator-visible notice about a projected
    # `listing_cardinality_mode`: either its supplied value was unrecognized
    # and a domain's structural default was substituted, or its value was
    # honored but arrived under the deprecated ingestion key. A pool's
    # absence means nothing is owed, not that data is missing.
    listing_cardinality_mode_explanations: dict[str, dict[str, str]] | None = None
    # Each configured site's latest publication derivation, as ``holds``,
    # ``refusals``, and ``reports``: every entry a reason code with the pool or
    # resource it concerns and any detail. A site derived cleanly has empty
    # lists; a site no publication cycle has derived since start is absent.
    publication_derivation: dict[str, dict[str, list[dict[str, Any]]]] | None = None
    storefront_domains: tuple[dict[str, str], ...] | None = None
    #: The storefront-to-provisioning contract major this storefront speaks,
    #: read from its own installed `compute_provisioning` wheel. A cutover
    #: requires every participant to report its pin before mutations resume,
    #: and two deployments can disagree only if their wheels differ.
    #:
    #: Declared here because this model is what the route returns: the status
    #: handler builds `HealthResponse(**body)`, so a key the service puts in
    #: its status dict and this model does not name never reaches a caller.
    #: Any field added to that dict has to be added here too.
    #:
    #: Distinct from `storefront_domains[].contract_version`, which is a
    #: domain contribution's own version and a different axis. Optional so
    #: `GET /health`, which shares this model and reports neither, stays
    #: valid.
    provisioning_contract_version: str | None = None
    #: Storefront policies a counterparty may read before committing data,
    #: keyed by subject -- for example the introduction retention window,
    #: which a buyer reads before handing over contact details. Absent when
    #: the storefront discloses nothing.
    disclosures: dict[str, dict[str, Any]] | None = None
    #: Every lifecycle loop by name: its controller state and the outcome of
    #: its most recent cycle, the publication loop's included. Present on
    #: system status, not on the liveness probes.
    lifecycle: dict[str, LoopStatus] | None = None
    #: Each composed settlement mechanism's readiness as its registration
    #: projects it: whether it is ready, each blocker's code, message, and kind,
    #: and the public details the mechanism reports. Present on system status,
    #: not on the liveness probes.
    settlement: tuple[dict[str, Any], ...] | None = None


class AdminPauseResponse(BaseModel):
    paused: bool
    message: str = ""


#: Largest page `GET /api/v1/system/events` will return, and the bound its
#: `limit` query parameter is validated against.
#:
#: One constant for the route's validation and the store's clamp because the
#: two disagreeing is unobservable: a caller asking for exactly the cap gets a
#: full page either way, and cannot tell it apart from a page with more behind
#: it. `StageEventResponse.truncated` is what makes the difference reportable,
#: and it is only meaningful if the cap has a single definition.
STAGE_EVENT_PAGE_CAP = 500


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int
    #: Whether more rows matched the query than this page carries.
    #:
    #: The server's to report, not the client's to infer. `count == limit` is
    #: ambiguous -- it is equally a log that ended exactly at the page boundary
    #: and a log that continues past it -- and the requested limit may have been
    #: lowered by `STAGE_EVENT_PAGE_CAP` before the page was cut, so the caller
    #: does not necessarily know which boundary it hit. A reader that filters
    #: this page is only entitled to conclusions about the whole log when this
    #: is false.
    truncated: bool = False



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