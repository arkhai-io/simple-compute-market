"""Marketplace listing API routes.

Wire vocabulary uses ``listing_id`` / ``seller`` / ``buyer`` /
``seller_attestation`` / ``buyer_attestation``. The DB columns are
still on the legacy ``order_*`` / ``*_attestation`` names; the
translation lives in :func:`order_to_dict` (response shaping) and
:func:`_listing_body_to_columns` here (request shaping). The DB
column rename happens in a later slice.
"""

import logging
import time
from typing import Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from src.db.database import get_db
from src.db.models import Agent, Listing, OrderStatusEnum
from src.api.utils import (
    find_agent_by_id,
    order_to_dict,
    validate_order_status,
    matches_resource_filters,
    find_symmetric_order,
    verify_order_signature,
)

_MAX_TIMESTAMP_SKEW = 300  # 5 minutes


def _check_timestamp(timestamp: int) -> None:
    if abs(int(time.time()) - timestamp) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=401, detail="Timestamp too old or too far in future (max 5 minutes)")

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Wire ↔ DB column translation
# ---------------------------------------------------------------------------

_WIRE_TO_DB_KEYS = {
    "listing_id": "order_id",
    "seller": "order_maker",
    "buyer": "order_taker",
    "seller_attestation": "maker_attestation",
    "buyer_attestation": "taker_attestation",
}


def _listing_body_to_columns(body: dict) -> dict:
    """Translate a wire request body to DB column keys.

    Accepts the listings vocabulary (``listing_id``, ``seller``,
    ``buyer``, ``seller_attestation``, ``buyer_attestation``) and
    returns a dict using the legacy DB column names so the existing
    SQLAlchemy code can keep using them unchanged.
    """
    out = dict(body)
    for wire_key, db_key in _WIRE_TO_DB_KEYS.items():
        if wire_key in out and db_key not in out:
            out[db_key] = out.pop(wire_key)
    return out


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

    # Verify signature if agent has an owner
    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)
    if agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated agents")
        _check_timestamp(timestamp)
        if not verify_order_signature("create_listing", agent.agent_id, timestamp, signature, agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Translate wire keys to DB column names
    order_data = _listing_body_to_columns(body)

    # Use canonical agent_id for FK in Listing
    agent_id_for_order = agent.agent_id

    # Extract listing identifier
    order_id = order_data.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="listing_id is required")

    existing_order = db.query(Listing).filter(Listing.order_id == order_id).first()

    if existing_order:
        update_fields = {
            "order_maker": order_data.get("order_maker"),
            "offer_resource": order_data.get("offer_resource"),
            "demand_resource": order_data.get("demand_resource"),
            "duration_hours": order_data.get("duration_hours"),
            "maker_attestation": order_data.get("maker_attestation"),
            "taker_attestation": order_data.get("taker_attestation"),
            "oracle_address": order_data.get("oracle_address"),
        }
        for field, value in update_fields.items():
            if value is not None:
                setattr(existing_order, field, value)

        if "status" in order_data:
            existing_order.status = validate_order_status(order_data["status"])

        existing_order.updated_at = datetime.utcnow()
        order = existing_order
    else:
        status_str = order_data.get("status", "open")
        order = Listing(
            order_id=order_id,
            agent_id=agent_id_for_order,
            order_maker=order_data.get("order_maker", ""),
            order_taker=order_data.get("order_taker"),
            offer_resource=order_data.get("offer_resource", {}),
            demand_resource=order_data.get("demand_resource", {}),
            duration_hours=order_data.get("duration_hours", 1),
            maker_attestation=order_data.get("maker_attestation"),
            taker_attestation=order_data.get("taker_attestation"),
            oracle_address=order_data.get("oracle_address"),
            status=validate_order_status(status_str),
        )
        db.add(order)

    db.commit()
    db.refresh(order)

    return {
        "listing_id": order.order_id,
        "agentId": agent.agent_id,
        "status": order.status.value,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
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

    orders = query.order_by(desc(Listing.created_at)).offset(offset).limit(limit).all()

    return {
        "items": [order_to_dict(order) for order in orders],
        "count": len(orders),
    }


@router.get("/listings")
async def query_listings(
    offer_resource_type: Optional[str] = Query(None, description="Filter by offer resource type (compute/token)"),
    demand_resource_type: Optional[str] = Query(None, description="Filter by demand resource type (compute/token)"),
    region: Optional[str] = Query(None, description="Filter by region"),
    gpu_model: Optional[str] = Query(None, description="Filter by GPU model"),
    sla: Optional[float] = Query(None, description="Filter by SLA"),
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

    orders = query.order_by(desc(Listing.created_at)).offset(offset).limit(limit).all()

    filtered_items = [
        order_to_dict(order)
        for order in orders
        if matches_resource_filters(
            order,
            offer_resource_type=offer_resource_type,
            demand_resource_type=demand_resource_type,
            region=region,
            gpu_model=gpu_model,
            sla=sla,
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
    order = db.query(Listing).filter(Listing.order_id == listing_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Listing not found")

    # Verify signature if the maker agent has an owner
    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)
    signer_agent_id = body.pop("signer_agent_id", None)

    maker_agent = find_agent_by_id(db, order.agent_id)
    if maker_agent and maker_agent.owner:
        if not signature or timestamp is None or not signer_agent_id:
            raise HTTPException(
                status_code=401,
                detail="signature, timestamp, and signer_agent_id required for authenticated listings"
            )
        _check_timestamp(timestamp)

        signer_agent = find_agent_by_id(db, signer_agent_id)
        if not signer_agent or not signer_agent.owner:
            raise HTTPException(status_code=403, detail="Signer agent not registered or has no owner")

        is_maker = (signer_agent.agent_id == order.agent_id)
        if not is_maker and order.order_taker is not None:
            raise HTTPException(status_code=403, detail="Only the listing seller can update after a buyer is assigned")

        if not verify_order_signature("update_listing", listing_id, timestamp, signature, signer_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Translate wire keys to DB column names for the update set
    updates = _listing_body_to_columns(body)

    original_order_maker = order.order_maker
    original_offer_resource = order.offer_resource
    original_demand_resource = order.demand_resource

    symmetric_order = None
    needs_symmetric_lookup = (
        "order_taker" in updates
        or ("maker_attestation" in updates and order.order_taker)
        or ("taker_attestation" in updates and order.order_taker)
        or ("oracle_address" in updates and order.order_taker)
    )
    if needs_symmetric_lookup:
        if "order_taker" in updates:
            temp_taker = updates["order_taker"]
            original_taker = order.order_taker
            order.order_taker = temp_taker
            try:
                symmetric_order = find_symmetric_order(
                    db, order, original_offer_resource, original_demand_resource
                )
            finally:
                order.order_taker = original_taker
        else:
            symmetric_order = find_symmetric_order(
                db, order, original_offer_resource, original_demand_resource
            )

    if "status" in updates:
        order.status = validate_order_status(updates["status"])
    if "order_taker" in updates:
        order.order_taker = updates["order_taker"]
    if "taker_attestation" in updates:
        order.taker_attestation = updates["taker_attestation"]
    if "maker_attestation" in updates:
        order.maker_attestation = updates["maker_attestation"]
    if "oracle_address" in updates:
        order.oracle_address = updates["oracle_address"]
    order.updated_at = datetime.utcnow()

    if symmetric_order:
        if "status" in updates:
            symmetric_order.status = validate_order_status(updates["status"])
        if "order_taker" in updates:
            symmetric_order.order_taker = original_order_maker
        if "maker_attestation" in updates and order.maker_attestation:
            symmetric_order.taker_attestation = order.maker_attestation
        if "taker_attestation" in updates and order.taker_attestation:
            symmetric_order.maker_attestation = order.taker_attestation
        if "oracle_address" in updates and order.oracle_address:
            symmetric_order.oracle_address = order.oracle_address
        symmetric_order.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(order)
        if symmetric_order:
            db.refresh(symmetric_order)
    except Exception as e:
        db.rollback()
        logger.error(f"[REGISTRY] Failed to update listings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update listings: {e}")

    return {
        "listing_id": order.order_id,
        "status": order.status.value,
        "updated_at": order.updated_at.isoformat(),
        "symmetric_listing_updated": symmetric_order.order_id if symmetric_order else None,
    }


@router.get("/listings/{listing_id}")
async def get_listing(
    listing_id: str = Path(..., description="Listing ID"),
    db: Session = Depends(get_db),
):
    """Get a single listing by ID."""
    order = db.query(Listing).filter(Listing.order_id == listing_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Listing not found")

    return {
        "listing": order_to_dict(order),
    }


@router.delete("/listings/{listing_id}", status_code=204)
async def delete_listing(
    listing_id: str = Path(..., description="Listing ID"),
    signature: Optional[str] = Query(None, description="EIP-191 signature"),
    timestamp: Optional[int] = Query(None, description="Unix timestamp of signature"),
    db: Session = Depends(get_db),
):
    """Remove a listing from the registry. Requires signature from the listing seller's owner."""
    order = db.query(Listing).filter(Listing.order_id == listing_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Listing not found")

    maker_agent = find_agent_by_id(db, order.agent_id)
    if maker_agent and maker_agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated listings")
        _check_timestamp(timestamp)
        if not verify_order_signature("delete_listing", listing_id, timestamp, signature, maker_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    db.delete(order)
    db.commit()

    return None
