"""HTTP request/response models for the Listings controller.

Domain types (ComputeResource, TokenResource, Listing) live in domain_models.py.
"""
from __future__ import annotations

from typing import Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Filter params — Depends() factory for GET /api/v1/listings
# ---------------------------------------------------------------------------

class ListingFilterParams(BaseModel):
    """Query parameters for GET /api/v1/listings.

    Instantiated via ``Depends(listing_filter_params)`` so FastAPI validates
    all filters through Pydantic rather than as individual method parameters,
    which mangled the @cbv route signature.
    """
    model_config = ConfigDict(extra="ignore")

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    status: str | None = None
    paused: bool | None = None
    region: str | None = None
    gpu_model: str | None = None
    cpu_type: str | None = None
    host_disk_type: str | None = None
    motherboard: str | None = None
    gpu_interconnect: str | None = None
    virtualization_type: str | None = None
    static_ip: bool | None = None
    datacenter_grade: bool | None = None
    sla: float | None = None
    gpu_count_min: int | None = None
    vcpu_count_min: int | None = None
    ram_gb_min: int | None = None
    disk_gb_min: int | None = None
    host_cpu_cores_min: int | None = None
    host_ram_gb_min: int | None = None
    host_disk_gb_min: int | None = None
    total_gpu_count_min: int | None = None
    nic_speed_gbps_min: int | None = None
    internet_download_mbps_min: int | None = None
    internet_upload_mbps_min: int | None = None
    open_ports_count_min: int | None = None

    def to_spec_kwargs(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field_name in (
            "region", "gpu_model", "cpu_type", "host_disk_type", "motherboard",
            "gpu_interconnect", "virtualization_type", "static_ip", "datacenter_grade",
            "sla", "gpu_count_min", "vcpu_count_min", "ram_gb_min", "disk_gb_min",
            "host_cpu_cores_min", "host_ram_gb_min", "host_disk_gb_min",
            "total_gpu_count_min", "nic_speed_gbps_min",
            "internet_download_mbps_min", "internet_upload_mbps_min",
            "open_ports_count_min",
        ):
            v = getattr(self, field_name)
            if v is not None:
                result[field_name] = v
        return result


async def listing_filter_params(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    paused: bool | None = Query(default=None),
    region: str | None = Query(default=None),
    gpu_model: str | None = Query(default=None),
    cpu_type: str | None = Query(default=None),
    host_disk_type: str | None = Query(default=None),
    motherboard: str | None = Query(default=None),
    gpu_interconnect: str | None = Query(default=None),
    virtualization_type: str | None = Query(default=None),
    static_ip: bool | None = Query(default=None),
    datacenter_grade: bool | None = Query(default=None),
    sla: float | None = Query(default=None),
    gpu_count_min: int | None = Query(default=None),
    vcpu_count_min: int | None = Query(default=None),
    ram_gb_min: int | None = Query(default=None),
    disk_gb_min: int | None = Query(default=None),
    host_cpu_cores_min: int | None = Query(default=None),
    host_ram_gb_min: int | None = Query(default=None),
    host_disk_gb_min: int | None = Query(default=None),
    total_gpu_count_min: int | None = Query(default=None),
    nic_speed_gbps_min: int | None = Query(default=None),
    internet_download_mbps_min: int | None = Query(default=None),
    internet_upload_mbps_min: int | None = Query(default=None),
    open_ports_count_min: int | None = Query(default=None),
) -> ListingFilterParams:
    return ListingFilterParams(
        limit=limit, offset=offset, status=status, paused=paused,
        region=region, gpu_model=gpu_model, cpu_type=cpu_type,
        host_disk_type=host_disk_type, motherboard=motherboard,
        gpu_interconnect=gpu_interconnect, virtualization_type=virtualization_type,
        static_ip=static_ip, datacenter_grade=datacenter_grade, sla=sla,
        gpu_count_min=gpu_count_min, vcpu_count_min=vcpu_count_min,
        ram_gb_min=ram_gb_min, disk_gb_min=disk_gb_min,
        host_cpu_cores_min=host_cpu_cores_min, host_ram_gb_min=host_ram_gb_min,
        host_disk_gb_min=host_disk_gb_min, total_gpu_count_min=total_gpu_count_min,
        nic_speed_gbps_min=nic_speed_gbps_min,
        internet_download_mbps_min=internet_download_mbps_min,
        internet_upload_mbps_min=internet_upload_mbps_min,
        open_ports_count_min=open_ports_count_min,
    )


# ---------------------------------------------------------------------------
# Request models
# listing_id is in the URL path for all lifecycle operations.
# ---------------------------------------------------------------------------

class CreateListingRequest(BaseModel):
    """Body for POST /api/v1/listings/create."""
    offer: dict[str, Any] = Field(description="Offered resource (compute or token dict)")
    demand: dict[str, Any] = Field(description="Demanded resource (compute or token dict)")
    max_duration_seconds: int | None = None
    paused: bool = Field(
        default=False,
        description=(
            "If true the listing is created paused and NOT published to the "
            "registry until POST /api/v1/listings/{id}/resume is called."
        ),
    )


class RefundRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/refund.
    listing_id is in the path; this body contains the payment details only.

    ``buyer_address`` defaults to the listing's recorded buyer (the
    storefront DB knows it once a deal closes); pass explicitly to
    override.
    """
    buyer_address: str | None = None
    amount: float | None = None
    token: str | None = None


class ClaimRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/claim."""
    escrow_uid: str
    fulfillment_uid: str


class ReclaimRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/reclaim."""
    escrow_uid: str


class ArbitrateRequest(BaseModel):
    """Body for POST /api/v1/listings/{listing_id}/arbitrate."""
    escrow_uid: str | None = None
    fulfillment_uid: str | None = None
    decision: bool = True


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ListingResponse(BaseModel):
    """Single listing — returned by GET /api/v1/listings/{id}."""
    listing_id: str
    status: str
    paused: bool = False
    offer_resource: Any = None    # dict or JSON string from SQLite
    demand_resource: Any = None   # dict or JSON string from SQLite
    max_duration_seconds: int | None = None
    seller: str | None = None
    model_config = ConfigDict(extra="allow")


class ListingListResponse(BaseModel):
    """Response for GET /api/v1/listings."""
    listings: list[dict[str, Any]]
    count: int
    limit: int
    offset: int
    total_after_filter: int | None = None


class PauseListingResponse(BaseModel):
    """Response for POST /api/v1/listings/{id}/pause and /resume."""
    listing_id: str
    paused: bool
    registry_status: str = ""
    message: str = ""


class CreateListingResponse(BaseModel):
    """Response for POST /api/v1/listings/create."""
    status: str
    listing_id: str | None = None
    root_agent_response: str = ""


class CloseListingResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/close."""
    status: str
    listing_id: str
    root_agent_response: str = ""


class RefundResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/refund."""
    status: str
    listing_id: str
    tx_hash: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    token: dict[str, Any] | None = None
    amount_raw: int | None = None
    block_number: int | None = None


class ClaimResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/claim."""
    status: str
    listing_id: str
    escrow_uid: str | None = None
    fulfillment_uid: str | None = None
    collect_result: str | None = None


class ReclaimResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/reclaim."""
    status: str
    listing_id: str
    escrow_uid: str | None = None
    reclaim_result: str | None = None


class ArbitrateResponse(BaseModel):
    """Response for POST /api/v1/listings/{listing_id}/arbitrate."""
    status: str
    listing_id: str
    fulfillment_uid: str | None = None
    decision: bool = True
    decisions_count: int = 0
    note: str = ""


class AdminEvaluateCreateResponse(BaseModel):
    """Response for POST /api/v1/admin/listings/evaluate-create.

    Returns what the policy pipeline *would* do for a given CreateListingRequest
    without writing anything to SQLite or the registry.
    """
    would_create: bool
    action: str
    listing_id_preview: str | None = None
    policy_used: str | None = None
    reason: str | None = None


class AdminEvaluateCloseResponse(BaseModel):
    """Response for POST /api/v1/admin/listings/{listing_id}/evaluate-close.

    Returns what the policy pipeline *would* do for a close event.
    """
    would_close: bool
    action: str
    listing_id: str
    policy_used: str | None = None
    reason: str | None = None
