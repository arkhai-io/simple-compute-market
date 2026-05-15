"""Marketplace listing API routes.

Wire vocabulary and DB column names are now in sync (post-Slice 4):
``listing_id`` / ``seller`` / ``buyer`` / ``seller_attestation`` /
``buyer_attestation``. No translation layer.
"""

import logging
import time
from typing import Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.db.database import get_db
from src.db.models import Agent, Listing, OrderStatusEnum
from src.api.utils import (
    find_agent_by_id,
    order_to_dict,
    validate_order_status,
    matches_resource_filters,
    verify_order_signature,
)

_MAX_TIMESTAMP_SKEW = 300  # 5 minutes


def _check_timestamp(timestamp: int) -> None:
    if abs(int(time.time()) - timestamp) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=401, detail="Timestamp too old or too far in future (max 5 minutes)")

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agents/{agent_id}/listings", status_code=201)
async def publish_listing(
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format)"),
    body: dict = Body(..., description="Marketplace listing data"),
    db: Session = Depends(get_db),
):
    """Publish a marketplace listing to the registry."""
    agent = find_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)
    if agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated agents")
        _check_timestamp(timestamp)
        if not verify_order_signature("create_listing", agent.agent_id, timestamp, signature, agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    agent_id_for_listing = agent.agent_id

    listing_id = body.get("listing_id")
    if not listing_id:
        raise HTTPException(status_code=400, detail="listing_id is required")

    existing = db.query(Listing).filter(Listing.listing_id == listing_id).first()

    if existing:
        update_fields = {
            "seller": body.get("seller"),
            "offer_resource": body.get("offer_resource"),
            "demand_resource": body.get("demand_resource"),
            "max_duration_seconds": body.get("max_duration_seconds"),
            "oracle_address": body.get("oracle_address"),
        }
        for field, value in update_fields.items():
            if value is not None:
                setattr(existing, field, value)

        if "status" in body:
            existing.status = validate_order_status(body["status"])

        existing.updated_at = datetime.utcnow()
        listing = existing
    else:
        status_str = body.get("status", "open")
        listing = Listing(
            listing_id=listing_id,
            agent_id=agent_id_for_listing,
            seller=body.get("seller", ""),
            buyer=body.get("buyer"),
            offer_resource=body.get("offer_resource", {}),
            demand_resource=body.get("demand_resource", {}),
            max_duration_seconds=body.get("max_duration_seconds"),
            oracle_address=body.get("oracle_address"),
            status=validate_order_status(status_str),
        )
        db.add(listing)

    db.commit()
    db.refresh(listing)

    return {
        "listing_id": listing.listing_id,
        "agentId": agent.agent_id,
        "status": listing.status.value,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


@router.get("/agents/{agent_id}/listings")
async def get_agent_listings(
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format)"),
    status: Optional[str] = Query(None, description="Filter by listing status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List marketplace listings for a specific agent."""
    agent = find_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    query = db.query(Listing).filter(Listing.agent_id == agent.agent_id)

    if status:
        status_enum = validate_order_status(status)
        query = query.filter(Listing.status == status_enum)

    listings = query.order_by(desc(Listing.created_at)).offset(offset).limit(limit).all()

    return {
        "items": [order_to_dict(listing) for listing in listings],
        "count": len(listings),
    }


@router.get("/listings")
async def query_listings(
    offer_resource_type: Optional[str] = Query(None, description="Filter by offer resource type (compute/token)"),
    demand_resource_type: Optional[str] = Query(None, description="Filter by demand resource type (compute/token)"),
    # Equality filters
    region: Optional[str] = Query(None, description="Filter by region"),
    gpu_model: Optional[str] = Query(None, description="Filter by GPU model"),
    sla: Optional[float] = Query(None, description="Filter by SLA (exact match)"),
    cpu_type: Optional[str] = Query(None, description="Filter by host CPU model string"),
    host_disk_type: Optional[str] = Query(None, description="Filter by host disk model"),
    motherboard: Optional[str] = Query(None, description="Filter by host motherboard model"),
    gpu_interconnect: Optional[str] = Query(None, description="Filter by GPU interconnect (nvlink|nvswitch|pcie_only|infiniband)"),
    virtualization_type: Optional[str] = Query(None, description="Filter by virtualization mode (bare_metal|vm|container)"),
    static_ip: Optional[bool] = Query(None, description="Filter by static-IP availability"),
    datacenter_grade: Optional[bool] = Query(None, description="Filter by datacenter grade"),
    # Slice ">=" filters
    gpu_count_min: Optional[int] = Query(None, ge=0, description="Minimum slice GPU count"),
    vcpu_count_min: Optional[int] = Query(None, ge=0, description="Minimum slice vCPU count"),
    ram_gb_min: Optional[int] = Query(None, ge=0, description="Minimum slice RAM in GB"),
    disk_gb_min: Optional[int] = Query(None, ge=0, description="Minimum slice disk in GB"),
    # Host-context ">=" filters
    host_cpu_cores_min: Optional[int] = Query(None, ge=0, description="Minimum host CPU cores"),
    host_ram_gb_min: Optional[int] = Query(None, ge=0, description="Minimum host RAM in GB"),
    host_disk_gb_min: Optional[int] = Query(None, ge=0, description="Minimum host disk in GB"),
    total_gpu_count_min: Optional[int] = Query(None, ge=0, description="Minimum total GPUs on host"),
    nic_speed_gbps_min: Optional[int] = Query(None, ge=0, description="Minimum host NIC speed (Gbps)"),
    internet_download_mbps_min: Optional[int] = Query(None, ge=0, description="Minimum host internet downlink (Mbps)"),
    internet_upload_mbps_min: Optional[int] = Query(None, ge=0, description="Minimum host internet uplink (Mbps)"),
    open_ports_count_min: Optional[int] = Query(None, ge=0, description="Minimum externally-routable open ports"),
    # Listing-level
    status: Optional[str] = Query("open", description="Filter by listing status"),
    bidirectional: bool = Query(False, description="Enable bidirectional matching"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """Query marketplace listings with filters (supports bidirectional matching)."""
    query = db.query(Listing)

    if status:
        status_enum = validate_order_status(status)
        query = query.filter(Listing.status == status_enum)

    listings = query.order_by(desc(Listing.created_at)).offset(offset).limit(limit).all()

    filtered_items = [
        order_to_dict(listing)
        for listing in listings
        if matches_resource_filters(
            listing,
            offer_resource_type=offer_resource_type,
            demand_resource_type=demand_resource_type,
            region=region,
            gpu_model=gpu_model,
            sla=sla,
            cpu_type=cpu_type,
            host_disk_type=host_disk_type,
            motherboard=motherboard,
            gpu_interconnect=gpu_interconnect,
            virtualization_type=virtualization_type,
            static_ip=static_ip,
            datacenter_grade=datacenter_grade,
            gpu_count_min=gpu_count_min,
            vcpu_count_min=vcpu_count_min,
            ram_gb_min=ram_gb_min,
            disk_gb_min=disk_gb_min,
            host_cpu_cores_min=host_cpu_cores_min,
            host_ram_gb_min=host_ram_gb_min,
            host_disk_gb_min=host_disk_gb_min,
            total_gpu_count_min=total_gpu_count_min,
            nic_speed_gbps_min=nic_speed_gbps_min,
            internet_download_mbps_min=internet_download_mbps_min,
            internet_upload_mbps_min=internet_upload_mbps_min,
            open_ports_count_min=open_ports_count_min,
            bidirectional=bidirectional,
        )
    ]

    return {
        "items": filtered_items,
        "count": len(filtered_items),
        "bidirectional": bidirectional,
    }


@router.put("/listings/{listing_id}")
async def update_listing(
    listing_id: str = Path(..., description="Listing ID"),
    body: dict = Body(..., description="Listing updates"),
    db: Session = Depends(get_db),
):
    """Update a listing (e.g., mark as accepted). Also updates the corresponding symmetric listing."""
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)
    signer_agent_id = body.pop("signer_agent_id", None)

    seller_agent = find_agent_by_id(db, listing.agent_id)
    if seller_agent and seller_agent.owner:
        if not signature or timestamp is None or not signer_agent_id:
            raise HTTPException(
                status_code=401,
                detail="signature, timestamp, and signer_agent_id required for authenticated listings"
            )
        _check_timestamp(timestamp)

        signer_agent = find_agent_by_id(db, signer_agent_id)
        if not signer_agent or not signer_agent.owner:
            raise HTTPException(status_code=403, detail="Signer agent not registered or has no owner")

        is_seller = (signer_agent.agent_id == listing.agent_id)
        if not is_seller and listing.buyer is not None:
            raise HTTPException(status_code=403, detail="Only the listing seller can update after a buyer is assigned")

        if not verify_order_signature("update_listing", listing_id, timestamp, signature, signer_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    if "status" in body:
        listing.status = validate_order_status(body["status"])
    if "buyer" in body:
        listing.buyer = body["buyer"]
    if "oracle_address" in body:
        listing.oracle_address = body["oracle_address"]
    listing.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(listing)
    except Exception as e:
        db.rollback()
        logger.error(f"[REGISTRY] Failed to update listing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update listing: {e}")

    return {
        "listing_id": listing.listing_id,
        "status": listing.status.value,
        "updated_at": listing.updated_at.isoformat(),
    }


@router.get("/listings/{listing_id}")
async def get_listing(
    listing_id: str = Path(..., description="Listing ID"),
    db: Session = Depends(get_db),
):
    """Get a single listing by ID."""
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    return {
        "listing": order_to_dict(listing),
    }


@router.delete("/listings/{listing_id}", status_code=204)
async def delete_listing(
    listing_id: str = Path(..., description="Listing ID"),
    signature: Optional[str] = Query(None, description="EIP-191 signature"),
    timestamp: Optional[int] = Query(None, description="Unix timestamp of signature"),
    db: Session = Depends(get_db),
):
    """Remove a listing from the registry. Requires signature from the listing seller's owner."""
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    seller_agent = find_agent_by_id(db, listing.agent_id)
    if seller_agent and seller_agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated listings")
        _check_timestamp(timestamp)
        if not verify_order_signature("delete_listing", listing_id, timestamp, signature, seller_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    db.delete(listing)
    db.commit()

    return None
