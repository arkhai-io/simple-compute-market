"""HTTP request/response models for System and Admin controllers."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    paused: bool | None = None
    agent_id: str | None = None
    chain_id: int | None = None
    resource_count: int | None = None


class PolicyEvaluateRequest(BaseModel):
    event_type: str = "order_create"
    offer: dict[str, Any] | None = None
    demand: dict[str, Any] | None = None
    max_duration_seconds: int | None = None
    policy_components: list[str] = Field(
        description=(
            "Callable names to evaluate against (e.g. ['oc.action.make_offer_from_order_create']). "
            "The endpoint checks each name against the CALLABLE_REGISTRY and runs the pipeline. "
            "No DB lookup is performed — this is a pure data operation."
        ),
    )


class PolicyComponentResponse(BaseModel):
    name: str
    resolvable: bool


class PolicyEvaluateResponse(BaseModel):
    action: str
    policy_used: str | None = None
    components: list[str] = Field(default_factory=list)  # callable names
    resolvable: bool = True
    reason: str | None = None


class ImportErrorResponse(BaseModel):
    module: str
    error: str


class SeedPoliciesResponse(BaseModel):
    callable_registry_count: int
    callables: list[str]
    seeded_policies: list[str]
    import_errors: list[ImportErrorResponse]


class SeededPolicyInfo(BaseModel):
    policy_name: str
    trigger_type: str
    components: list[str] = Field(default_factory=list)
    components_resolvable: bool


class PolicyStatusResponse(BaseModel):
    callable_count: int
    callable_registry: dict[str, Any] = Field(default_factory=dict)
    seeded_policies: list[SeededPolicyInfo]


class AdminPauseResponse(BaseModel):
    paused: bool
    message: str = ""


class ReleaseReservationsResponse(BaseModel):
    """Response from POST /api/v1/admin/portfolio/release-reservations.

    ``released_count`` is the number of resources transitioned from
    ``reserved`` back to ``available``. ``resource_ids`` lists each one.
    Both are zero/empty when no resources were reserved at call time.
    """
    released_count: int
    resource_ids: list[str]


class ImportResourcesResponse(BaseModel):
    """Response for POST /api/v1/admin/portfolio/resources/import."""
    imported_count: int
    failed_count: int
    total_rows: int


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int


class RegistryAgentReadyResponse(BaseModel):
    """Response from GET /api/v1/system/wait-for-registry-agent.

    ``ready=True`` means ``checks.registry_auth`` returned a definitive
    non-pending value — either ``"ok"`` (agent indexed and owner verified)
    or a terminal error (``"owner_mismatch"``, ``"unconfigured"``, etc.).
    ``ready=False`` means the request timed out while the registry was still
    returning ``"agent_not_found"`` (indexing in progress).

    ``registry_auth`` carries the raw value from ``registry_auth_check()``
    so callers can distinguish ``"ok"`` from ``"owner_mismatch"``.
    ``elapsed_ms`` is the approximate server-side wait time.
    """

    ready: bool
    registry_auth: str
    elapsed_ms: int


class ResourcePatchRequest(BaseModel):
    """Request body for PATCH /api/v1/admin/portfolio/resources/{resource_id}.

    All fields are optional; only supplied (non-None) fields are written.
    This makes the endpoint suitable for any partial update: releasing a lease
    (state='available', clear lease_end_utc), forcing a state transition for
    testing, or updating arbitrary resource attributes.

    ``state``: any valid resource state string ('available', 'reserved',
    'leased', 'deleted').

    ``attributes``: merged into the existing JSON attributes column.  Pass
    ``{"lease_end_utc": None}`` to clear the lease timestamp when releasing.

    ``lease_end_utc``: convenience shorthand for setting
    ``attributes.lease_end_utc``; ignored if ``attributes`` also sets it.
    """

    state: Optional[str] = Field(
        default=None,
        description="New resource state. Only written if provided.",
    )
    attributes: Optional[dict] = Field(
        default=None,
        description=(
            "Partial attribute patch. Keys present in this dict are merged "
            "into the existing attributes JSON; absent keys are untouched. "
            "Pass null values to clear individual attribute keys."
        ),
    )


class ResourcePatchResponse(BaseModel):
    """Response from PATCH /api/v1/admin/portfolio/resources/{resource_id}.

    Returns the full resource row after the patch so callers can confirm
    what was written without a second GET.
    """

    resource_id: str
    state: Optional[str] = None
    attributes: Optional[dict] = None
    updated: bool = Field(
        description="True if any field was actually changed; False if the "
                    "row was already in the requested state (idempotent call)."
    )
