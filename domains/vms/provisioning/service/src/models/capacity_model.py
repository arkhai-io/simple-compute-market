"""Pydantic models for the site-authority capacity API.

The ``/api/v1/capacity`` surface mirrors the
``core_storefront.capacity.CapacityClient`` contract: claims and deal
refs are opaque mappings (the claim speaks this site's resource-domain
vocabulary, the deal ref carries the storefront's bookkeeping keys), and
match/allocation payloads are returned verbatim as dicts so the remote
client can hand them to callers exactly like the embedded adapter does.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ResourceRegisterRequest(BaseModel):
    """Body accepted by ``PUT /api/v1/capacity/resources/{resource_id}``."""

    total_units: int = Field(
        ge=0,
        description="Unit count this resource contributes (e.g. GPUs).",
    )
    resource_type: str = Field(default="compute.gpu")
    resource_subtype: Optional[str] = Field(
        default=None, description="e.g. the GPU model slug ('h200')."
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Resource-domain attributes (vm_host, gpu_model, region, …). "
            "Market schema (pricing, escrows) stays on the storefront."
        ),
    )
    enabled: bool = Field(default=True)


class ResourceListResponse(BaseModel):
    resources: list[dict[str, Any]]
    total: int


class SnapshotResponse(BaseModel):
    resources: list[dict[str, Any]]


class ProbeRequest(BaseModel):
    claim: dict[str, Any] = Field(default_factory=dict)


class MatchResponse(BaseModel):
    match: Optional[dict[str, Any]] = None


class ReserveRequest(BaseModel):
    claim: dict[str, Any] = Field(default_factory=dict)
    deal_ref: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Opaque storefront bookkeeping keys (listing_id, escrow_uid, "
            "owner callback), recorded on the allocation so deal-scoped "
            "events route back to the owning storefront."
        ),
    )
    ttl_seconds: Optional[float] = Field(
        default=None,
        gt=0,
        description=(
            "Optional soft-hold TTL (two-phase reserve): the reservation "
            "auto-expires unless committed before the deadline."
        ),
    )


class AllocationResponse(BaseModel):
    allocation: Optional[dict[str, Any]] = None


class CommitRequest(BaseModel):
    resource_id: str
    lease_end_utc: str = Field(
        description="When the lease ends (ISO-8601 or 'YYYY-MM-DD HH:MM')."
    )
    idempotency_ref: Optional[str] = None


class ReleaseRequest(BaseModel):
    """Body accepted by ``POST /api/v1/capacity/releases``.

    Identify the allocation either directly or by the deal ref it was
    reserved under (escrow_uid).
    """

    allocation_id: Optional[str] = None
    deal_ref: dict[str, Any] = Field(default_factory=dict)
    failure_reason: Optional[str] = Field(
        default=None,
        description="Recorded on the allocation when releasing after a failure.",
    )
    failure_message: Optional[str] = None


class TruncateLeaseRequest(BaseModel):
    lease_end_utc: str


class CapacityEventsResponse(BaseModel):
    """Versioned event page for ``GET /api/v1/capacity/events``.

    ``latest_version`` reflects the feed head even when ``events`` is a
    truncated page, so pollers know to keep paging; a subscriber that
    detects a gap against what it last applied resyncs from a snapshot.
    """

    events: list[dict[str, Any]]
    latest_version: int
