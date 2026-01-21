"""Unit tests for order route endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.db.database import get_db
from src.db.models import MarketOrder, OrderStatusEnum


@pytest.fixture
def client(db_session):
    """Create a test client with database dependency override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_order(client, sample_agent):
    """Test creating a new order."""
    response = client.post(
        f"/agents/{sample_agent.agent_id}/orders",
        json={
            "order_id": "test-order-create",
            "order_maker": "http://localhost:8001/.well-known/agent-card.json",
            "offer_resource": {"gpu_model": "A100", "region": "us-west"},
            "demand_resource": {"token": "USDC"},
            "duration_hours": 3600,
            "status": "open",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["order_id"] == "test-order-create"
    assert data["status"] == "open"


def test_create_order_duplicate(client, sample_agent, sample_order):
    """Test creating order with existing order_id updates it."""
    response = client.post(
        f"/agents/{sample_agent.agent_id}/orders",
        json={
            "order_id": sample_order.order_id,
            "order_maker": "http://localhost:8001/.well-known/agent-card.json",
            "offer_resource": {"gpu_model": "H100", "region": "us-east"},
            "demand_resource": {"token": "USDC"},
            "duration_hours": 7200,
            "status": "closed",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["order_id"] == sample_order.order_id
    assert data["status"] == "closed"


def test_create_order_invalid_agent(client):
    """Test creating order with invalid agent ID."""
    response = client.post(
        "/agents/invalid-agent-id/orders",
        json={
            "order_id": "test-order",
            "offer_resource": {"gpu_model": "A100"},
            "demand_resource": {"token": "USDC"},
        },
    )
    assert response.status_code == 404
    assert "Agent not found" in response.json()["detail"]


def test_create_order_missing_order_id(client, sample_agent):
    """Test creating order with missing order_id."""
    response = client.post(
        f"/agents/{sample_agent.agent_id}/orders",
        json={
            "offer_resource": {"gpu_model": "A100"},
            "demand_resource": {"token": "USDC"},
        },
    )
    assert response.status_code == 400
    assert "order_id is required" in response.json()["detail"]


def test_get_agent_orders(client, sample_agent, db_session):
    """Test listing orders for an agent."""
    # Create multiple orders
    for i in range(3):
        order = MarketOrder(
            order_id=f"test-order-{i}",
            agent_id=sample_agent.agent_id,
            order_maker="http://localhost:8001/.well-known/agent-card.json",
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            duration_hours=3600,
            status=OrderStatusEnum.open,
        )
        db_session.add(order)
    db_session.commit()
    
    response = client.get(f"/agents/{sample_agent.agent_id}/orders")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["count"] == 3


def test_get_agent_orders_filtered_by_status(client, sample_agent, db_session):
    """Test filtering orders by status."""
    # Create orders with different statuses
    order_open = MarketOrder(
        order_id="test-order-open",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    order_closed = MarketOrder(
        order_id="test-order-closed",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.closed,
    )
    db_session.add(order_open)
    db_session.add(order_closed)
    db_session.commit()
    
    response = client.get(f"/agents/{sample_agent.agent_id}/orders?status=open")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["status"] == "open"


def test_query_orders_with_filters(client, db_session, sample_agent):
    """Test querying orders with resource filters."""
    order = MarketOrder(
        order_id="test-order-filter",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    
    response = client.get("/orders?offer_resource_type=compute&region=us-west")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) >= 1
    assert any(item["order_id"] == "test-order-filter" for item in data["items"])


def test_query_orders_bidirectional(client, db_session, sample_agent):
    """Test bidirectional matching."""
    # Create order A: offer GPU, demand token
    order_a = MarketOrder(
        order_id="order-a",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    # Create order B: offer token, demand GPU
    order_b = MarketOrder(
        order_id="order-b",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8002/.well-known/agent-card.json",
        offer_resource={"token": "USDC"},
        demand_resource={"gpu_model": "A100"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order_a)
    db_session.add(order_b)
    db_session.commit()
    
    response = client.get("/orders?bidirectional=true")
    assert response.status_code == 200
    data = response.json()
    assert data["bidirectional"] is True
    assert len(data["items"]) >= 2


def test_update_order(client, sample_order):
    """Test updating an order."""
    response = client.put(
        f"/orders/{sample_order.order_id}",
        json={"status": "accepted"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"


def test_update_order_symmetric(client, db_session, sample_agent):
    """Test updating order updates symmetric order."""
    # Create order A: offer GPU, demand token
    order_a = MarketOrder(
        order_id="order-a-symmetric",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        order_taker="http://localhost:8002/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100"},
        demand_resource={"token": "USDC"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    # Create order B: offer token, demand GPU (symmetric)
    order_b = MarketOrder(
        order_id="order-b-symmetric",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8002/.well-known/agent-card.json",
        offer_resource={"token": "USDC"},
        demand_resource={"gpu_model": "A100"},
        duration_hours=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order_a)
    db_session.add(order_b)
    db_session.commit()
    
    response = client.put(
        f"/orders/{order_a.order_id}",
        json={"status": "accepted"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data.get("symmetric_order_updated") is not None


def test_delete_order(client, sample_order):
    """Test deleting an order."""
    response = client.delete(f"/orders/{sample_order.order_id}")
    assert response.status_code == 204


def test_delete_order_not_found(client):
    """Test deleting non-existent order."""
    response = client.delete("/orders/nonexistent")
    assert response.status_code == 404

