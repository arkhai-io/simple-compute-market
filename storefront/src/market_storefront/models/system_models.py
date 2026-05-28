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


class ImportRowError(BaseModel):
    """One failed CSV row in an /admin/portfolio/resources/import response.

    `row_number` is 1-based and matches what a spreadsheet shows
    (header = 1, first data row = 2). `errors` is the list of validation
    messages from the importer for that row.
    """
    row_number: int
    resource_id: str | None = None
    resource_type: str | None = None
    errors: list[str]


class ImportResourcesResponse(BaseModel):
    """Response for POST /api/v1/admin/portfolio/resources/import."""
    imported_count: int
    failed_count: int
    total_rows: int
    errors: list[ImportRowError] = []


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int


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
