"""Market order-related API routes."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from src.db.database import get_db
from src.db.models import Agent, MarketOrder, OrderStatusEnum
from src.api.utils import (
    find_agent_by_id,
    order_to_dict,
    validate_order_status,
    matches_resource_filters,
    find_symmetric_order,
    verify_order_signature,
)
from src.utils.time import utcnow

_MAX_TIMESTAMP_SKEW = 300  # 5 minutes


def _check_timestamp(timestamp: int) -> None:
    if abs(int(time.time()) - timestamp) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=401, detail="Timestamp too old or too far in future (max 5 minutes)")

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agents/{agent_id}/orders", status_code=201)
async def publish_order(
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format)"),
    order_data: dict = Body(..., description="Market order data"),
    db: Session = Depends(get_db),
):
    """Publish a market order to the registry (supports both directions: compute supply and compute demand)"""
    agent = find_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify signature if agent has an owner
    signature = order_data.pop("signature", None)
    timestamp = order_data.pop("timestamp", None)
    if agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated agents")
        _check_timestamp(timestamp)
        if not verify_order_signature("create_order", agent.agent_id, timestamp, signature, agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Use canonical agent_id for FK in MarketOrder
    agent_id_for_order = agent.agent_id

    # Extract order fields
    order_id = order_data.get("order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")
    
    # Check if order already exists
    existing_order = db.query(MarketOrder).filter(MarketOrder.order_id == order_id).first()
    
    if existing_order:
        # Update existing order
        update_fields = {
            "order_maker": order_data.get("order_maker"),
            "offer_resource": order_data.get("offer_resource"),
            "demand_resource": order_data.get("demand_resource"),
            "duration_hours": order_data.get("duration_hours"),
            "maker_attestation": order_data.get("maker_attestation"),
            "taker_attestation": order_data.get("taker_attestation"),
        }
        for field, value in update_fields.items():
            if value is not None:
                setattr(existing_order, field, value)
        
        if "status" in order_data:
            existing_order.status = validate_order_status(order_data["status"])
        
        existing_order.updated_at = utcnow()
        order = existing_order
    else:
        # Create new order
        status_str = order_data.get("status", "open")
        order = MarketOrder(
            order_id=order_id,
            agent_id=agent_id_for_order,
            order_maker=order_data.get("order_maker", ""),
            order_taker=order_data.get("order_taker"),
            offer_resource=order_data.get("offer_resource", {}),
            demand_resource=order_data.get("demand_resource", {}),
            duration_hours=order_data.get("duration_hours", 1),
            maker_attestation=order_data.get("maker_attestation"),
            taker_attestation=order_data.get("taker_attestation"),
            status=validate_order_status(status_str),
        )
        db.add(order)
    
    db.commit()
    db.refresh(order)
    
    return {
        "order_id": order.order_id,
        "agentId": agent.agent_id,  # Single agentId field (canonical format)
        "status": order.status.value,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


@router.get("/agents/{agent_id}/orders")
async def get_agent_orders(
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format)"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List orders for a specific agent"""
    agent = find_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Use canonical agent_id for FK lookup
    query = db.query(MarketOrder).filter(MarketOrder.agent_id == agent.agent_id)
    
    if status:
        status_enum = validate_order_status(status)
        query = query.filter(MarketOrder.status == status_enum)
    
    orders = query.order_by(desc(MarketOrder.created_at)).offset(offset).limit(limit).all()
    
    return {
        "items": [order_to_dict(order) for order in orders],
        "count": len(orders),
    }


@router.get("/orders")
async def query_orders(
    offer_resource_type: Optional[str] = Query(None, description="Filter by offer resource type (compute/token)"),
    demand_resource_type: Optional[str] = Query(None, description="Filter by demand resource type (compute/token)"),
    region: Optional[str] = Query(None, description="Filter by region"),
    gpu_model: Optional[str] = Query(None, description="Filter by GPU model"),
    sla: Optional[float] = Query(None, description="Filter by SLA"),
    status: Optional[str] = Query("open", description="Filter by order status"),
    bidirectional: bool = Query(False, description="Enable bidirectional matching"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """Query orders with filters (supports bidirectional matching)"""
    query = db.query(MarketOrder)
    
    # Filter by status
    if status:
        status_enum = validate_order_status(status)
        query = query.filter(MarketOrder.status == status_enum)
    
    orders = query.order_by(desc(MarketOrder.created_at)).offset(offset).limit(limit).all()
    
    # Filter in Python for complex resource matching
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


@router.put("/orders/{order_id}")
async def update_order(
    order_id: str = Path(..., description="Order ID"),
    updates: dict = Body(..., description="Order updates"),
    db: Session = Depends(get_db),
):
    """Update an order (e.g., mark as accepted). Also updates the corresponding symmetric order."""
    order = db.query(MarketOrder).filter(MarketOrder.order_id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Verify signature if the maker agent has an owner
    signature = updates.pop("signature", None)
    timestamp = updates.pop("timestamp", None)
    signer_agent_id = updates.pop("signer_agent_id", None)

    maker_agent = find_agent_by_id(db, order.agent_id)
    if maker_agent and maker_agent.owner:
        if not signature or timestamp is None or not signer_agent_id:
            raise HTTPException(
                status_code=401,
                detail="signature, timestamp, and signer_agent_id required for authenticated orders"
            )
        _check_timestamp(timestamp)

        signer_agent = find_agent_by_id(db, signer_agent_id)
        if not signer_agent or not signer_agent.owner:
            raise HTTPException(status_code=403, detail="Signer agent not registered or has no owner")

        is_maker = (signer_agent.agent_id == order.agent_id)
        # A new taker can claim an unmatched order; once a taker is set only the maker can update
        if not is_maker and order.order_taker is not None:
            raise HTTPException(status_code=403, detail="Only the order maker can update after a taker is assigned")

        if not verify_order_signature("update_order", order_id, timestamp, signature, signer_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    original_order_maker = order.order_maker
    original_offer_resource = order.offer_resource
    original_demand_resource = order.demand_resource
    
    symmetric_order = None
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
    
    if "status" in updates:
        order.status = validate_order_status(updates["status"])
    if "order_taker" in updates:
        order.order_taker = updates["order_taker"]
    if "taker_attestation" in updates:
        order.taker_attestation = updates["taker_attestation"]
    if "maker_attestation" in updates:
        order.maker_attestation = updates["maker_attestation"]
    order.updated_at = utcnow()
    
    if symmetric_order:
        if "status" in updates:
            symmetric_order.status = validate_order_status(updates["status"])
        if "order_taker" in updates:
            symmetric_order.order_taker = original_order_maker
        if "maker_attestation" in updates and order.maker_attestation:
            symmetric_order.taker_attestation = order.maker_attestation
        if "taker_attestation" in updates and order.taker_attestation:
            symmetric_order.maker_attestation = order.taker_attestation
        symmetric_order.updated_at = utcnow()
    
    try:
        db.commit()
        db.refresh(order)
        if symmetric_order:
            db.refresh(symmetric_order)
    except Exception as e:
        db.rollback()
        logger.error(f"[REGISTRY] Failed to update orders: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update orders: {e}")
    
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "updated_at": order.updated_at.isoformat(),
        "symmetric_order_updated": symmetric_order.order_id if symmetric_order else None,
    }


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str = Path(..., description="Order ID"),
    db: Session = Depends(get_db),
):
    """Get a single order by ID."""
    order = db.query(MarketOrder).filter(MarketOrder.order_id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "order": order_to_dict(order),
    }


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(
    order_id: str = Path(..., description="Order ID"),
    signature: Optional[str] = Query(None, description="EIP-191 signature"),
    timestamp: Optional[int] = Query(None, description="Unix timestamp of signature"),
    db: Session = Depends(get_db),
):
    """Remove an order from the registry. Requires signature from the order maker's owner."""
    order = db.query(MarketOrder).filter(MarketOrder.order_id == order_id).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    maker_agent = find_agent_by_id(db, order.agent_id)
    if maker_agent and maker_agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated orders")
        _check_timestamp(timestamp)
        if not verify_order_signature("delete_order", order_id, timestamp, signature, maker_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    db.delete(order)
    db.commit()

    return None
