"""Market order-related API routes."""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from src.db.database import get_db
from src.db.models import Agent, MarketOrder, OrderStatusEnum
from src.api.utils import parse_erc8004_canonical_id, get_resource_type, resources_match

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agents/{agent_id}/orders", status_code=201)
async def publish_order(
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format or integer PK)"),
    order_data: dict = Body(..., description="Market order data"),
    db: Session = Depends(get_db),
):
    """Publish a market order to the registry (supports both directions: compute supply and compute demand)"""
    # Try to parse as integer (PK)
    try:
        agent_id_int = int(agent_id)
        agent = db.query(Agent).filter(Agent.id == agent_id_int).first()
    except ValueError:
        agent = None
    
    # If not found by PK, try canonical ID
    if not agent:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    
    # Fallback: try to parse as canonical ID and lookup by components
    if not agent:
        try:
            chain_id, identity_registry, onchain_agent_id = parse_erc8004_canonical_id(agent_id)
            agent = db.query(Agent).filter(
                and_(
                    Agent.chain_id == chain_id,
                    Agent.identity_registry == identity_registry,
                    Agent.onchain_agent_id == onchain_agent_id
                )
            ).first()
        except ValueError:
            pass
    
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
        existing_order.order_maker = order_data.get("order_maker", existing_order.order_maker)
        existing_order.offer_resource = order_data.get("offer_resource", existing_order.offer_resource)
        existing_order.demand_resource = order_data.get("demand_resource", existing_order.demand_resource)
        existing_order.duration = order_data.get("duration", existing_order.duration)
        existing_order.maker_attestation = order_data.get("maker_attestation", existing_order.maker_attestation)
        existing_order.taker_attestation = order_data.get("taker_attestation", existing_order.taker_attestation)
        existing_order.status = OrderStatusEnum(order_data.get("status", existing_order.status.value))
        existing_order.updated_at = datetime.utcnow()
        order = existing_order
    else:
        # Create new order
        order = MarketOrder(
            order_id=order_id,
            agent_id=agent_id_for_order,  # Use agent_id (string) for FK
            order_maker=order_data.get("order_maker", ""),
            order_taker=order_data.get("order_taker"),
            offer_resource=order_data.get("offer_resource", {}),
            demand_resource=order_data.get("demand_resource", {}),
            duration=order_data.get("duration", 1),
            maker_attestation=order_data.get("maker_attestation"),
            taker_attestation=order_data.get("taker_attestation"),
            status=OrderStatusEnum(order_data.get("status", "open")),
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
    agent_id: str = Path(..., description="Agent ID (canonical eip155:... format or integer PK)"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List orders for a specific agent"""
    # Try to parse as integer (PK)
    try:
        agent_id_int = int(agent_id)
        agent = db.query(Agent).filter(Agent.id == agent_id_int).first()
    except ValueError:
        agent = None
    
    # If not found by PK, try canonical ID
    if not agent:
        agent = db.query(Agent).filter(Agent.agent_id == agent_id).first()
    
    # Fallback: try to parse as canonical ID and lookup by components
    if not agent:
        try:
            chain_id, identity_registry, onchain_agent_id = parse_erc8004_canonical_id(agent_id)
            agent = db.query(Agent).filter(
                and_(
                    Agent.chain_id == chain_id,
                    Agent.identity_registry == identity_registry,
                    Agent.onchain_agent_id == onchain_agent_id
                )
            ).first()
        except ValueError:
            pass
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Use canonical agent_id for FK lookup
    query = db.query(MarketOrder).filter(MarketOrder.agent_id == agent.agent_id)
    
    if status:
        try:
            status_enum = OrderStatusEnum(status)
            query = query.filter(MarketOrder.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    orders = query.order_by(desc(MarketOrder.created_at)).offset(offset).limit(limit).all()
    
    return {
        "items": [
            {
                "order_id": order.order_id,
                "order_maker": order.order_maker,
                "order_taker": order.order_taker,
                "offer_resource": order.offer_resource,
                "demand_resource": order.demand_resource,
                "duration": order.duration,
                "maker_attestation": order.maker_attestation,
                "taker_attestation": order.taker_attestation,
                "status": order.status.value,
                "created_at": order.created_at.isoformat(),
                "updated_at": order.updated_at.isoformat(),
            }
            for order in orders
        ],
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
        try:
            status_enum = OrderStatusEnum(status)
            query = query.filter(MarketOrder.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    orders = query.order_by(desc(MarketOrder.created_at)).offset(offset).limit(limit).all()
    
    # Filter in Python for complex resource matching
    filtered_items = []
    for order in orders:
        offer_res = order.offer_resource or {}
        demand_res = order.demand_resource or {}
        
        # When bidirectional=True, skip strict resource type filtering
        # Client-side matching will handle bidirectional matching
        if not bidirectional:
            # Filter by offer resource type (only when not bidirectional)
            if offer_resource_type:
                res_type = get_resource_type(offer_res)
                if res_type != offer_resource_type.lower():
                    continue
            
            # Filter by demand resource type (only when not bidirectional)
            if demand_resource_type:
                res_type = get_resource_type(demand_res)
                if res_type != demand_resource_type.lower():
                    continue
        
        # Filter by region (if compute resource) - applies to both directions
        if region and "region" in offer_res:
            if offer_res.get("region") != region:
                continue
        if region and "region" in demand_res:
            if demand_res.get("region") != region:
                continue
        
        # Filter by GPU model (if compute resource) - applies to both directions
        if gpu_model and "gpu_model" in offer_res:
            if offer_res.get("gpu_model") != gpu_model:
                continue
        if gpu_model and "gpu_model" in demand_res:
            if demand_res.get("gpu_model") != gpu_model:
                continue
        
        # Filter by SLA (if compute resource) - applies to both directions
        if sla is not None and "sla" in offer_res:
            if offer_res.get("sla") != sla:
                continue
        if sla is not None and "sla" in demand_res:
            if demand_res.get("sla") != sla:
                continue
        
        filtered_items.append({
            "order_id": order.order_id,
            "agent_id": order.agent_id,
            "order_maker": order.order_maker,
            "order_taker": order.order_taker,
            "offer_resource": offer_res,
            "demand_resource": demand_res,
            "duration": order.duration,
            "maker_attestation": order.maker_attestation,
            "taker_attestation": order.taker_attestation,
            "status": order.status.value,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
        })
    
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
        try:
            order.status = OrderStatusEnum(updates["status"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {updates['status']}")
    
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
    # Symmetric order: offer_resource == original_order.demand_resource AND
    #                  demand_resource == original_order.offer_resource AND
    #                  order_maker == original_order.order_taker (the agent accepting)
    symmetric_order = None
    if order.order_taker:  # Only look for symmetric order if we have a taker
        symmetric_orders = db.query(MarketOrder).filter(
            and_(
                MarketOrder.order_id != order_id,  # Not the same order
                MarketOrder.order_maker == order.order_taker,  # Maker is the taker of original order
            )
        ).all()
        
        # Find the one where resources are swapped
        for candidate in symmetric_orders:
            if (resources_match(candidate.offer_resource, original_demand_resource) and
                resources_match(candidate.demand_resource, original_offer_resource)):
                symmetric_order = candidate
                break
    
    if symmetric_order:
        logger.info(f"[REGISTRY] Found symmetric order {symmetric_order.order_id} for order {order_id}")
        
        # Update symmetric order with swapped fields
        if "status" in updates:
            try:
                symmetric_order.status = OrderStatusEnum(updates["status"])
            except ValueError:
                pass  # Already validated above
        
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

