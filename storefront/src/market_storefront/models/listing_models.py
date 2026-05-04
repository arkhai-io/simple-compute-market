"""HTTP request/response models for the Listings controller.

Domain types (ComputeResource, TokenResource, Listing) live in domain_models.py.
These models describe the wire shapes for the listings REST API only.
"""
from __future__ import annotations

from typing import Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Filter params — used via Depends() on list_listings to avoid the
# @cbv + many Annotated[Query] params signature problem.
# ---------------------------------------------------------------------------

class ListingFilterParams(BaseModel):
    """Query parameters for GET /api/v1/listings.

    Instantiated via ``Depends(listing_filter_params)`` so FastAPI
    validates all 20+ filters through Pydantic rather than as individual
    method parameters, which mangled the @cbv route signature.
    """
    model_config = ConfigDict(extra="ignore")

    # Pagination
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    # Listing-level filters
    status: str | None = None
    paused: bool | None = None

    # Spec equality filters
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

    # Spec numeric-min filters
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
        """Extract non-None spec filter fields for matches_listing_filters()."""
        result: dict[str, Any] = {}
        for field in (
            "region", "gpu_model", "cpu_type", "host_disk_type", "motherboard",
            "gpu_interconnect", "virtualization_type", "static_ip", "datacenter_grade",
            "sla", "gpu_count_min", "vcpu_count_min", "ram_gb_min", "disk_gb_min",
            "host_cpu_cores_min", "host_ram_gb_min", "host_disk_gb_min",
            "total_gpu_count_min", "nic_speed_gbps_min",
            "internet_download_mbps_min", "internet_upload_mbps_min",
            "open_ports_count_min",
        ):
            v = getattr(self, field)
            if v is not None:
                result[field] = v
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
    """Depends() factory that produces a validated ListingFilterParams."""
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
# Create / close / escrow operation request models
# ---------------------------------------------------------------------------

class CreateListingRequest(BaseModel):
    """Body for POST /listings/create."""
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


class CloseListingRequest(BaseModel):
    """Body for POST /listings/close."""
    listing_id: str


class RefundRequest(BaseModel):
    """Body for POST /listings/refund."""
    listing_id: str
    buyer_address: str
    amount: float | None = None
    token: str | None = None


class ClaimRequest(BaseModel):
    """Body for POST /listings/claim."""
    listing_id: str
    escrow_uid: str
    fulfillment_uid: str


class ReclaimRequest(BaseModel):
    """Body for POST /listings/reclaim."""
    listing_id: str
    escrow_uid: str


class ArbitrateRequest(BaseModel):
    """Body for POST /listings/arbitrate."""
    listing_id: str
    escrow_uid: str | None = None
    fulfillment_uid: str | None = None
    decision: bool = True


class DiscoverRequest(BaseModel):
    """Body for POST /listings/discover."""
    listing_id: str
    include_active: bool = False


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PauseListingResponse(BaseModel):
    listing_id: str
    paused: bool
    registry_status: str = ""
    message: str = ""
