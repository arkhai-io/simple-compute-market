"""Pydantic models for the site-authority capacity API.

The ``/api/v1/capacity`` surface mirrors the
``core_storefront.capacity.SiteCapacityAuthority`` contract: claims and deal
refs are opaque mappings (the claim speaks this site's resource-domain
vocabulary, the deal ref carries the storefront's bookkeeping keys), and
match/reservation payloads are returned verbatim as dicts so the remote
client can hand them to callers exactly like the embedded adapter does.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from .declarations import CapacityDeclarationFields, DeclaredCapacity


class ResourceRegisterRequest(CapacityDeclarationFields):
    """Body accepted by ``PUT /api/v1/capacity/resources/{resource_id}``.

    The declaration's fields, with the resource id taken from the path. Two
    fields differ from a declaration for the endpoint's existing callers:
    ``resource_type`` defaults, and ``capacity`` may be replaced by the
    legacy scalar ``total_units``.
    """

    total_units: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Legacy scalar total of the composition's mirror dimension. Used "
            "only when ``capacity`` is omitted; when both are given they must "
            "agree on that dimension."
        ),
    )
    resource_type: str = Field(default="compute.gpu")
    capacity: Optional[DeclaredCapacity] = Field(
        default=None,
        description=(
            "Multidimensional total capacity, authoritative for exactly the "
            "dimensions it names, e.g. {'gpu_count': 8, 'vcpu_count': 192, "
            "'ram_gb': 2048, 'disk_gb': 20000}. When omitted, the declaration "
            "is {<mirror dimension>: total_units}."
        ),
    )


class ResourceListResponse(BaseModel):
    resources: list[dict[str, Any]]
    total: int


class SnapshotResponse(BaseModel):
    resources: list[dict[str, Any]]


class ProbeRequest(BaseModel):
    claim: dict[str, Any] = Field(default_factory=dict)
    lease_start_utc: Optional[str] = Field(
        default=None,
        description="Requested lease start. Omit/null means now.",
    )
    lease_duration_seconds: Optional[int] = Field(
        default=None,
        gt=0,
        description="Requested lease duration in seconds for window-aware matching.",
    )


class MatchResponse(BaseModel):
    match: Optional[dict[str, Any]] = None


class ReserveRequest(BaseModel):
    claim: dict[str, Any] = Field(default_factory=dict)
    deal_ref: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Opaque storefront bookkeeping keys (listing_id, escrow_uid, "
            "owner callback), recorded on the reservation so deal-scoped "
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
    lease_start_utc: Optional[str] = Field(
        default=None,
        description="Requested lease start. Omit/null means now.",
    )
    lease_duration_seconds: Optional[int] = Field(
        default=None,
        gt=0,
        description="Requested lease duration in seconds for window-aware matching.",
    )


class ReservationResponse(BaseModel):
    reservation: Optional[dict[str, Any]] = None


class CommitRequest(BaseModel):
    # Optional: CapacityLedgerService.commit() ignores this value whenever
    # capacity_reservation_id is supplied, which every caller of this
    # endpoint does -- capacity_reservation_id arrives as this route's own
    # path parameter, not from this body, so a caller-supplied resource_id
    # can never reach the ledger's resource_id-only reservation lookup
    # (used only when a caller has a resource_id but no
    # capacity_reservation_id at all -- see CapacityLedgerService._find_reservation).
    # An ordinary pool-scoped reservation, per the opaque-reservation
    # boundary this endpoint's own reserve() response already enforces
    # (resource_id is stripped from what callers receive), has no
    # resource_id to supply here in the first place.
    resource_id: Optional[str] = None
    lease_start_utc: Optional[str] = Field(
        default=None,
        description="Lease start. Omit/null means now.",
    )
    lease_end_utc: Optional[str] = Field(
        default=None,
        description=(
            "Derived lease expiry timestamp. Omit for an open-ended commit."
        ),
    )
    idempotency_ref: Optional[str] = None


class ReleaseRequest(BaseModel):
    """Body accepted by ``POST /api/v1/capacity/releases``.

    Identify the reservation either directly or by the deal ref it was
    reserved under (escrow_uid).
    """

    capacity_reservation_id: Optional[str] = None
    deal_ref: dict[str, Any] = Field(default_factory=dict)
    failure_reason: Optional[str] = Field(
        default=None,
        description="Recorded on the reservation when releasing after a failure.",
    )
    failure_message: Optional[str] = None


class TruncateLeaseRequest(BaseModel):
    lease_end_utc: str


class ReservationListResponse(BaseModel):
    reservations: list[dict[str, Any]]
    total: int


class CapacityEventsResponse(BaseModel):
    """Versioned event page for ``GET /api/v1/capacity/events``.

    ``latest_version`` reflects the feed head even when ``events`` is a
    truncated page, so pollers know to keep paging; a subscriber that
    detects a gap against what it last applied resyncs from a snapshot.
    """

    events: list[dict[str, Any]]
    latest_version: int


class ProjectionIdentityResponse(BaseModel):
    revision: int
    digest: str


class ResourcePoolProjectionResponse(ProjectionIdentityResponse):
    resource_pools: list[dict[str, Any]]


class CapacityBucketProjectionResponse(ProjectionIdentityResponse):
    capacity_buckets: list[dict[str, Any]]
