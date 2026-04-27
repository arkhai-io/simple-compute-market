"""Integration test fixtures for the registry service.

``RegistryClient`` (async, httpx.AsyncClient + ASGITransport) is the only
httpx client that can drive an ASGI app in-process.  Tests are ``async def``
and the ``registry_client`` fixture is an async fixture — pytest-asyncio
handles both transparently because ``asyncio_mode = "auto"`` is set in
pyproject.toml.

``SyncRegistryClient`` is used in ``integration-tests/`` against real deployed
endpoints where a real network socket is available.

Database isolation
------------------
Each test gets its own in-memory SQLite session.  ``get_db`` is overridden
so the client's HTTP calls read and write to the same session the fixture
setup code used.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import httpx

from registry_client import RegistryClient, RegistryClientError
from src.main import app
from src.db.database import get_db


# ---------------------------------------------------------------------------
# Test constants — Hardhat/Anvil deterministic key pairs
# ---------------------------------------------------------------------------

MAKER_AGENT_ID = "eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:1"
TAKER_AGENT_ID = "eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:3"

MAKER_PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
MAKER_ADDRESS     = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"

TAKER_PRIVATE_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
TAKER_ADDRESS     = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"

IDENTITY_REGISTRY = "0x21df544947ba3e8b3c32561399e88b52dc8b2823"


# ---------------------------------------------------------------------------
# Core fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registry_client(db_session) -> RegistryClient:
    """``RegistryClient`` (async) wired to the FastAPI app via ASGITransport.

    No network socket is opened.  ``get_db`` is overridden so every HTTP
    call reads and writes to the test's isolated in-memory SQLite session.
    """
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    async with RegistryClient(
        "http://test",
        transport=httpx.ASGITransport(app=app),
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared entity fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_no_owner(db_session):
    from src.db.models import Agent
    agent = Agent(
        id=10,
        agent_id="eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:10",
        chain_id=31337,
        identity_registry=IDENTITY_REGISTRY,
        onchain_agent_id=10,
        registry_address=IDENTITY_REGISTRY,
        owner=None,
        token_uri="http://localhost:8010/.well-known/agent-card.json",
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


@pytest.fixture
def maker_agent(db_session):
    from src.db.models import Agent
    agent = Agent(
        id=1,
        agent_id=MAKER_AGENT_ID,
        chain_id=31337,
        identity_registry=IDENTITY_REGISTRY,
        onchain_agent_id=1,
        registry_address=IDENTITY_REGISTRY,
        owner=MAKER_ADDRESS,
        token_uri="http://localhost:8001/.well-known/agent-card.json",
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


@pytest.fixture
def taker_agent(db_session):
    from src.db.models import Agent
    agent = Agent(
        id=3,
        agent_id=TAKER_AGENT_ID,
        chain_id=31337,
        identity_registry=IDENTITY_REGISTRY,
        onchain_agent_id=3,
        registry_address=IDENTITY_REGISTRY,
        owner=TAKER_ADDRESS,
        token_uri="http://localhost:8003/.well-known/agent-card.json",
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


@pytest.fixture
def open_order(db_session, agent_no_owner):
    from src.db.models import MarketOrder, OrderStatusEnum
    order = MarketOrder(
        order_id="integ-open-order-1",
        agent_id=agent_no_owner.agent_id,
        order_maker=agent_no_owner.token_uri,
        offer_resource={"gpu_model": "A100", "region": "us-west", "quantity": 1, "sla": 99.0},
        demand_resource={"token": "USDC", "amount": 100.0},
        duration_hours=1,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


@pytest.fixture
def authenticated_open_order(db_session, maker_agent):
    from src.db.models import MarketOrder, OrderStatusEnum
    order = MarketOrder(
        order_id="integ-auth-order-1",
        agent_id=maker_agent.agent_id,
        order_maker=maker_agent.token_uri,
        offer_resource={"gpu_model": "A100", "region": "us-west", "quantity": 1, "sla": 99.0},
        demand_resource={"token": "USDC", "amount": 100.0},
        duration_hours=1,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order
