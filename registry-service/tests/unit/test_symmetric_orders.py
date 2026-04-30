"""Unit tests for symmetric order finding functionality."""

import pytest
from src.api.utils import find_symmetric_order
from src.db.models import Listing, OrderStatusEnum


def test_find_symmetric_order(db_session, sample_agent):
    """Test finding symmetric order."""
    # Create order A: offer GPU, demand token
    order_a = Listing(
        order_id="order-a",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        order_taker="http://localhost:8002/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order_a)
    
    # Create order B: offer token, demand GPU (symmetric)
    order_b = Listing(
        order_id="order-b",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8002/.well-known/agent-card.json",
        offer_resource={"token": "USDC"},
        demand_resource={"gpu_model": "A100", "region": "us-west"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order_b)
    db_session.commit()
    
    original_offer = order_a.offer_resource
    original_demand = order_a.demand_resource
    
    symmetric = find_symmetric_order(db_session, order_a, original_offer, original_demand)
    assert symmetric is not None
    assert symmetric.order_id == "order-b"


def test_find_symmetric_order_not_found(db_session, sample_agent):
    """Test symmetric order not found."""
    order = Listing(
        order_id="order-no-match",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        order_taker="http://localhost:8002/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    
    original_offer = order.offer_resource
    original_demand = order.demand_resource
    
    symmetric = find_symmetric_order(db_session, order, original_offer, original_demand)
    assert symmetric is None


def test_find_symmetric_order_no_taker(db_session, sample_agent):
    """Test symmetric order finding when order has no taker."""
    order = Listing(
        order_id="order-no-taker",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        order_taker=None,
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    
    original_offer = order.offer_resource
    original_demand = order.demand_resource
    
    symmetric = find_symmetric_order(db_session, order, original_offer, original_demand)
    assert symmetric is None

