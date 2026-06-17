"""VM provisioning payloads accepted by the storefront admin API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReleaseReservationsResponse(BaseModel):
    """Response from POST /api/v1/admin/portfolio/release-reservations."""

    released_count: int
    resource_ids: list[str]


class ReserveCapacityRequest(BaseModel):
    """Request body for POST /api/v1/admin/portfolio/reservations."""

    required_attributes: dict[str, Any] = Field(default_factory=dict)
    listing_id: str | None = None
    escrow_uid: str | None = None


class ReserveCapacityResponse(BaseModel):
    """Response from POST /api/v1/admin/portfolio/reservations."""

    allocation_id: str
    pool_id: str | None = None
    member_id: str | None = None
    resource_id: str
    gpu_count: int
    resource_state: str | None = None
    closed_listing_ids: list[str] = Field(default_factory=list)


class ImportRowError(BaseModel):
    """One failed CSV row in an /admin/portfolio/resources/import response."""

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


class ResourcePatchRequest(BaseModel):
    """Request body for PATCH /api/v1/admin/portfolio/resources/{resource_id}."""

    state: str | None = Field(
        default=None,
        description="New resource state. Only written if provided.",
    )
    attributes: dict | None = Field(
        default=None,
        description=(
            "Partial attribute patch. Keys present in this dict are merged "
            "into the existing attributes JSON; absent keys are untouched. "
            "Pass null values to clear individual attribute keys."
        ),
    )


class ResourcePatchResponse(BaseModel):
    """Response from PATCH /api/v1/admin/portfolio/resources/{resource_id}."""

    resource_id: str
    state: str | None = None
    attributes: dict | None = None
    updated: bool = Field(
        description="True if any field was actually changed; False if the "
        "row was already in the requested state (idempotent call)."
    )


class FulfillmentStartedEventRequest(BaseModel):
    allocation_id: str
    escrow_uid: str | None = None
    provider_id: str | None = None
    provider_job_id: str | None = None
    resource_id: str | None = None
    gpu_count: int | None = None


class FulfillmentFailedEventRequest(BaseModel):
    allocation_id: str
    escrow_uid: str | None = None
    provider_id: str | None = None
    provider_job_id: str | None = None
    resource_id: str | None = None
    reason: str | None = None
    message: str | None = None
    logs_ref: str | None = None


class UsageStartedEventRequest(BaseModel):
    allocation_id: str
    escrow_uid: str | None = None
    provider_id: str | None = None
    provider_lease_id: str | None = None
    resource_id: str | None = None
    vm_host: str | None = None
    vm_target: str | None = None
    gpu_count: int | None = None
    lease_end_utc: str | None = None


class ReleaseStartedEventRequest(BaseModel):
    allocation_id: str
    provider_lease_id: str | None = None
    vm_remove_job_id: str | None = None


class CapacityReleasedEventRequest(BaseModel):
    allocation_id: str
    provider_lease_id: str | None = None
    resource_id: str | None = None
    released_at: str | None = None


class FulfillmentEventResponse(BaseModel):
    allocation_id: str
    state: str
    resource_id: str | None = None
    gpu_count: int | None = None
    resource_state: str | None = None
    closed_listing_ids: list[str] = Field(default_factory=list)
    reopened_listing_ids: list[str] = Field(default_factory=list)
