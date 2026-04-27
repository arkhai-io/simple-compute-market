"""Unit tests for resource filtering functionality."""

import pytest
from src.api.utils import matches_resource_filters
from src.db.models import MarketOrder, OrderStatusEnum


def test_matches_resource_filters_compute(db_session, sample_agent):
    """Test compute resource filtering."""
    order = MarketOrder(
        order_id="test-order-compute",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    
    assert matches_resource_filters(order, offer_resource_type="compute") is True
    assert matches_resource_filters(order, offer_resource_type="token") is False


def test_matches_resource_filters_region(db_session, sample_agent):
    """Test region filtering."""
    order = MarketOrder(
        order_id="test-order-region",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    
    assert matches_resource_filters(order, region="us-west") is True
    assert matches_resource_filters(order, region="us-east") is False


def test_matches_resource_filters_bidirectional(db_session, sample_agent):
    """Test bidirectional filtering skips resource type check."""
    order = MarketOrder(
        order_id="test-order-bidirectional",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    
    # With bidirectional=True, resource type filtering is skipped
    assert matches_resource_filters(order, offer_resource_type="token", bidirectional=True) is True
    assert matches_resource_filters(order, offer_resource_type="token", bidirectional=False) is False


def test_matches_resource_filters_gpu_model(db_session, sample_agent):
    """Test GPU model filtering."""
    order = MarketOrder(
        order_id="test-order-gpu",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    
    assert matches_resource_filters(order, gpu_model="A100") is True
    assert matches_resource_filters(order, gpu_model="H100") is False


def test_matches_resource_filters_sla(db_session, sample_agent):
    """Test SLA filtering."""
    order = MarketOrder(
        order_id="test-order-sla",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west", "sla": 0.99},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    
    assert matches_resource_filters(order, sla=0.99) is True
    assert matches_resource_filters(order, sla=0.95) is False

