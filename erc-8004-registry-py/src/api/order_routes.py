"""Market order-related API routes."""

import logging
from typing import Optional
from datetime import datetime

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
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agents/{agent_id}/orders", status_code=201)
async def publish_order(
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format or integer PK)"),
    order_data: dict = Body(..., description="Market order data"),
    db: Session = Depends(get_db),
):
    """Publish a market order to the registry (supports both directions: compute supply and compute demand)"""
    agent = find_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
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
            "duration": order_data.get("duration"),
            "maker_attestation": order_data.get("maker_attestation"),
            "taker_attestation": order_data.get("taker_attestation"),
        }
        for field, value in update_fields.items():
            if value is not None:
                setattr(existing_order, field, value)
        
        if "status" in order_data:
            existing_order.status = validate_order_status(order_data["status"])
        
        existing_order.updated_at = datetime.utcnow()
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
            duration=order_data.get("duration", 1),
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
    
    # Store original values before updating
    original_order_maker = order.order_maker
    original_order_taker = order.order_taker
    original_offer_resource = order.offer_resource
    original_demand_resource = order.demand_resource
    
    # Update fields
    if "status" in updates:
        order.status = validate_order_status(updates["status"])
    
    if "order_taker" in updates:
        order.order_taker = updates["order_taker"]
    
    if "taker_attestation" in updates:
        order.taker_attestation = updates["taker_attestation"]
    
    if "maker_attestation" in updates:
        order.maker_attestation = updates["maker_attestation"]
    
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    
    # Find and update the corresponding symmetric order
    symmetric_order = find_symmetric_order(
        db, order, original_offer_resource, original_demand_resource
    )
    
    if symmetric_order:
        logger.info(f"[REGISTRY] Found symmetric order {symmetric_order.order_id} for order {order_id}")
        
        # Update symmetric order with swapped fields
        if "status" in updates:
            symmetric_order.status = validate_order_status(updates["status"])
        
        # For symmetric order: taker becomes the original maker
        if "order_taker" in updates:
            symmetric_order.order_taker = original_order_maker
        
        # Swap attestations: symmetric order's taker_attestation = original's maker_attestation
        if "maker_attestation" in updates and order.maker_attestation:
            symmetric_order.taker_attestation = order.maker_attestation
        
        # Swap attestations: symmetric order's maker_attestation = original's taker_attestation
        if "taker_attestation" in updates and order.taker_attestation:
            symmetric_order.maker_attestation = order.taker_attestation
        
        symmetric_order.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(symmetric_order)
        logger.info(f"[REGISTRY] Updated symmetric order {symmetric_order.order_id} status to {symmetric_order.status.value}")
    
    return {
        "order_id": order.order_id,
        "status": order.status.value,
        "updated_at": order.updated_at.isoformat(),
        "symmetric_order_updated": symmetric_order.order_id if symmetric_order else None,
    }


@router.delete("/orders/{order_id}", status_code=204)
async def delete_order(
    order_id: str = Path(..., description="Order ID"),
    db: Session = Depends(get_db),
):
    """Remove an order from the registry"""
    order = db.query(MarketOrder).filter(MarketOrder.order_id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    db.delete(order)
    db.commit()
    
    return None

