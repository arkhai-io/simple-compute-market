"""Integration tests for complete order lifecycle."""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.db.database import get_db
from src.db.models import Agent, MarketOrder, OrderStatusEnum


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


@pytest.fixture
def agent_a(db_session):
    """Create agent A for testing."""
    agent = Agent(
        id=1,
        agent_id="eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:1",
        chain_id=31337,
        identity_registry="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        onchain_agent_id=1,
        registry_address="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        owner="0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
        token_uri="http://localhost:8001/.well-known/agent-card.json",
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


@pytest.fixture
def agent_b(db_session):
    """Create agent B for testing."""
    agent = Agent(
        id=2,
        agent_id="eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:2",
        chain_id=31337,
        identity_registry="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        onchain_agent_id=2,
        registry_address="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        owner="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        token_uri="http://localhost:8002/.well-known/agent-card.json",
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


def test_complete_order_lifecycle(client, agent_a, agent_b, db_session):
    """Test complete order lifecycle."""
    # 1. Create order A: offer GPU, demand token
    response_a = client.post(
        f"/agents/{agent_a.agent_id}/orders",
        json={
            "order_id": "lifecycle-order-a",
            "order_maker": agent_a.token_uri,
            "offer_resource": {"gpu_model": "A100", "region": "us-west"},
            "demand_resource": {"token": "USDC"},
            "duration": 3600,
            "status": "open",
        },
    )
    assert response_a.status_code == 201
    order_a_id = response_a.json()["order_id"]
    
    # 2. Create order B: offer token, demand GPU
    response_b = client.post(
        f"/agents/{agent_b.agent_id}/orders",
        json={
            "order_id": "lifecycle-order-b",
            "order_maker": agent_b.token_uri,
            "offer_resource": {"token": "USDC"},
            "demand_resource": {"gpu_model": "A100", "region": "us-west"},
            "duration": 3600,
            "status": "open",
        },
    )
    assert response_b.status_code == 201
    order_b_id = response_b.json()["order_id"]
    
    # 3. Query orders with bidirectional=true
    response = client.get("/orders?bidirectional=true")
    assert response.status_code == 200
    data = response.json()
    assert data["bidirectional"] is True
    assert len(data["items"]) >= 2
    
    # 4. Verify matching orders are returned
    order_ids = [item["order_id"] for item in data["items"]]
    assert order_a_id in order_ids
    assert order_b_id in order_ids
    
    # 5. Update order A to accepted
    response = client.put(
        f"/orders/{order_a_id}",
        json={"status": "accepted", "order_taker": agent_b.token_uri},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    
    # 6. Verify symmetric order B is updated by querying agent B's orders
    response = client.get(f"/agents/{agent_b.agent_id}/orders")
    assert response.status_code == 200
    order_b_data = next(
        (item for item in response.json()["items"] if item["order_id"] == order_b_id),
        None
    )
    assert order_b_data is not None
    assert order_b_data["status"] == "accepted"
    assert order_b_data["order_taker"] == agent_a.token_uri
    
    # 7. Delete order A
    response = client.delete(f"/orders/{order_a_id}")
    assert response.status_code == 204
    
    # 8. Verify order A is removed
    response = client.get("/orders")
    order_ids = [item["order_id"] for item in response.json()["items"]]
    assert order_a_id not in order_ids


def test_agent_id_resolution_all_formats(client, agent_a, db_session):
    """Test agent ID resolution with all formats."""
    # 1. Register agent (already done via fixture)
    
    # 2. Create order using integer PK
    response_pk = client.post(
        f"/agents/{agent_a.id}/orders",
        json={
            "order_id": "test-pk-order",
            "order_maker": agent_a.token_uri,
            "offer_resource": {"gpu_model": "A100"},
            "demand_resource": {"token": "USDC"},
            "duration": 3600,
        },
    )
    assert response_pk.status_code == 201
    
    # 3. Create order using canonical ID
    response_canonical = client.post(
        f"/agents/{agent_a.agent_id}/orders",
        json={
            "order_id": "test-canonical-order",
            "order_maker": agent_a.token_uri,
            "offer_resource": {"gpu_model": "A100"},
            "demand_resource": {"token": "USDC"},
            "duration": 3600,
        },
    )
    assert response_canonical.status_code == 201
    
    # 4. Verify both resolve to same agent
    response = client.get(f"/agents/{agent_a.agent_id}/orders")
    assert response.status_code == 200
    order_ids = [item["order_id"] for item in response.json()["items"]]
    assert "test-pk-order" in order_ids
    assert "test-canonical-order" in order_ids

