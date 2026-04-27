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


def test_create_order(client, sample_agent_no_owner):
    """Test creating a new order (agent has no owner, no auth required)."""
    response = client.post(
        f"/agents/{sample_agent_no_owner.agent_id}/orders",
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


def test_create_order_duplicate(client, sample_agent_no_owner, sample_order_no_owner):
    """Test creating order with existing order_id updates it (no auth required)."""
    response = client.post(
        f"/agents/{sample_agent_no_owner.agent_id}/orders",
        json={
            "order_id": sample_order_no_owner.order_id,
            "order_maker": "http://localhost:8001/.well-known/agent-card.json",
            "offer_resource": {"gpu_model": "H100", "region": "us-east"},
            "demand_resource": {"token": "USDC"},
            "duration_hours": 7200,
            "status": "closed",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["order_id"] == sample_order_no_owner.order_id
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


def test_create_order_missing_order_id(client, sample_agent_no_owner):
    """Test creating order with missing order_id (no auth required)."""
    response = client.post(
        f"/agents/{sample_agent_no_owner.agent_id}/orders",
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


def test_update_order(client, sample_order_no_owner):
    """Test updating an order (agent has no owner, no auth required)."""
    response = client.put(
        f"/orders/{sample_order_no_owner.order_id}",
        json={"status": "accepted"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"


def test_update_order_symmetric(client, db_session, sample_agent_no_owner):
    """Test updating order updates symmetric order (no auth required)."""
    # Create order A: offer GPU, demand token
    order_a = MarketOrder(
        order_id="order-a-symmetric",
        agent_id=sample_agent_no_owner.agent_id,
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
        agent_id=sample_agent_no_owner.agent_id,
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
        # Include order_taker so the route triggers symmetric order lookup
        json={"status": "accepted", "order_taker": "http://localhost:8002/.well-known/agent-card.json"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "accepted"
    assert data.get("symmetric_order_updated") is not None


def test_delete_order(client, sample_order_no_owner):
    """Test deleting an order (agent has no owner, no auth required)."""
    response = client.delete(f"/orders/{sample_order_no_owner.order_id}")
    assert response.status_code == 204


def test_delete_order_not_found(client):
    """Test deleting non-existent order."""
    response = client.delete("/orders/nonexistent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Auth tests — sample_agent has owner set (0x3C44...293BC, Hardhat account #2)
# Private key: 0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a
# Taker agent uses Hardhat account #3: 0x90F79bf6EB2c4f870365E785982E1f101E93b906
# ---------------------------------------------------------------------------

MAKER_PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
TAKER_PRIVATE_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
TAKER_ADDRESS = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"


# --- publish (POST /agents/{agent_id}/orders) ---

def test_publish_order_authenticated_no_auth_returns_401(client, sample_agent):
    """Agents with an owner reject unsigned publish requests."""
    response = client.post(
        f"/agents/{sample_agent.agent_id}/orders",
        json={"order_id": "ord-auth-1", "offer_resource": {}, "demand_resource": {}},
    )
    assert response.status_code == 401


def test_publish_order_authenticated_valid_signature(client, sample_agent, sign_order_auth):
    """Valid signature from the agent owner allows publish."""
    auth = sign_order_auth(MAKER_PRIVATE_KEY, "create_order", sample_agent.agent_id)
    response = client.post(
        f"/agents/{sample_agent.agent_id}/orders",
        json={
            "order_id": "ord-auth-valid",
            "order_maker": "http://localhost:8001/",
            "offer_resource": {"gpu_model": "A100"},
            "demand_resource": {"token": "USDC"},
            "duration_hours": 1,
            **auth,
        },
    )
    assert response.status_code == 201


def test_publish_order_authenticated_wrong_signature_returns_401(client, sample_agent, sign_order_auth):
    """Signature from a different key is rejected."""
    auth = sign_order_auth(TAKER_PRIVATE_KEY, "create_order", sample_agent.agent_id)
    response = client.post(
        f"/agents/{sample_agent.agent_id}/orders",
        json={
            "order_id": "ord-auth-wrong",
            "offer_resource": {},
            "demand_resource": {},
            **auth,
        },
    )
    assert response.status_code == 401


def test_publish_order_authenticated_stale_timestamp_returns_401(client, sample_agent, sign_order_auth):
    """Timestamp older than 5 minutes is rejected."""
    import time
    # Build a valid signature but manually set a stale timestamp
    auth = sign_order_auth(MAKER_PRIVATE_KEY, "create_order", sample_agent.agent_id)
    auth["timestamp"] = int(time.time()) - 400  # backdate to 400s ago
    response = client.post(
        f"/agents/{sample_agent.agent_id}/orders",
        json={"order_id": "ord-stale", "offer_resource": {}, "demand_resource": {}, **auth},
    )
    assert response.status_code == 401


# --- update (PUT /orders/{order_id}) ---

def test_update_order_authenticated_no_auth_returns_401(client, sample_order):
    """Updating an owned order without auth is rejected."""
    response = client.put(f"/orders/{sample_order.order_id}", json={"status": "closed"})
    assert response.status_code == 401


def test_update_order_authenticated_as_maker(client, sample_order, sample_agent, sign_order_auth):
    """Maker can update their own order with a valid signature."""
    auth = sign_order_auth(MAKER_PRIVATE_KEY, "update_order", sample_order.order_id)
    response = client.put(
        f"/orders/{sample_order.order_id}",
        json={"status": "closed", "signer_agent_id": sample_agent.agent_id, **auth},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "closed"


def test_update_order_authenticated_wrong_signature_returns_401(client, sample_order, sample_agent, sign_order_auth):
    """Wrong signature on update is rejected."""
    auth = sign_order_auth(TAKER_PRIVATE_KEY, "update_order", sample_order.order_id)
    # signer_agent_id points to the maker's agent, but signature is from taker key — mismatch
    response = client.put(
        f"/orders/{sample_order.order_id}",
        json={"status": "closed", "signer_agent_id": sample_agent.agent_id, **auth},
    )
    assert response.status_code == 401


def test_update_order_as_new_taker(client, db_session, sample_order, sample_agent, sign_order_auth):
    """A registered taker agent can claim an unmatched order."""
    from src.db.models import Agent
    taker_agent = Agent(
        id=3,
        agent_id="eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:3",
        chain_id=31337,
        identity_registry="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        onchain_agent_id=3,
        registry_address="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        owner=TAKER_ADDRESS,
        token_uri="http://localhost:8003/.well-known/agent-card.json",
    )
    db_session.add(taker_agent)
    db_session.commit()

    auth = sign_order_auth(TAKER_PRIVATE_KEY, "update_order", sample_order.order_id)
    response = client.put(
        f"/orders/{sample_order.order_id}",
        json={
            "status": "accepted",
            "order_taker": "http://localhost:8003/",
            "signer_agent_id": taker_agent.agent_id,
            **auth,
        },
    )
    assert response.status_code == 200


def test_update_order_blocked_after_taker_assigned(client, db_session, sample_agent, sign_order_auth):
    """After a taker is assigned, a third party cannot update the order."""
    from src.db.models import Agent, MarketOrder
    # Order already has a taker
    order = MarketOrder(
        order_id="ord-with-taker",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/",
        order_taker="http://localhost:8003/",  # taker already set
        offer_resource={"gpu_model": "A100"},
        demand_resource={"token": "USDC"},
        duration_hours=1,
        status=OrderStatusEnum.accepted,
    )
    db_session.add(order)

    interloper = Agent(
        id=4,
        agent_id="eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:4",
        chain_id=31337,
        identity_registry="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        onchain_agent_id=4,
        registry_address="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        owner=TAKER_ADDRESS,
        token_uri="http://localhost:8004/.well-known/agent-card.json",
    )
    db_session.add(interloper)
    db_session.commit()

    auth = sign_order_auth(TAKER_PRIVATE_KEY, "update_order", order.order_id)
    response = client.put(
        f"/orders/{order.order_id}",
        json={"status": "closed", "signer_agent_id": interloper.agent_id, **auth},
    )
    assert response.status_code == 403


# --- delete (DELETE /orders/{order_id}) ---

def test_delete_order_authenticated_no_auth_returns_401(client, sample_order):
    """Deleting an owned order without a signature is rejected."""
    response = client.delete(f"/orders/{sample_order.order_id}")
    assert response.status_code == 401


def test_delete_order_authenticated_valid_signature(client, sample_order, sign_order_auth):
    """Maker can delete their own order with a valid signature."""
    auth = sign_order_auth(MAKER_PRIVATE_KEY, "delete_order", sample_order.order_id)
    response = client.delete(
        f"/orders/{sample_order.order_id}",
        params={"signature": auth["signature"], "timestamp": auth["timestamp"]},
    )
    assert response.status_code == 204


def test_delete_order_authenticated_wrong_signature_returns_401(client, sample_order, sign_order_auth):
    """Wrong key on delete is rejected."""
    auth = sign_order_auth(TAKER_PRIVATE_KEY, "delete_order", sample_order.order_id)
    response = client.delete(
        f"/orders/{sample_order.order_id}",
        params={"signature": auth["signature"], "timestamp": auth["timestamp"]},
    )
    assert response.status_code == 401

