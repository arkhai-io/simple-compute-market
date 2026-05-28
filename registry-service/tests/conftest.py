"""Pytest configuration and fixtures."""

import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.database import Base
from src.db.models import Agent, Listing, OrderStatusEnum


@pytest.fixture(scope="session")
def sign_order_auth():
    """Return a helper that builds EIP-191 auth fields for order mutations.

    Skips the calling test automatically if eth_account is not installed.
    """
    Account = pytest.importorskip("eth_account").Account
    encode_defunct = pytest.importorskip("eth_account.messages").encode_defunct

    def _sign(private_key: str, operation: str, resource_id: str) -> dict:
        ts = int(time.time())
        msg = encode_defunct(text=f"{operation}:{resource_id}:{ts}")
        sig = Account.sign_message(msg, private_key).signature.hex()
        return {"signature": sig, "timestamp": ts}

    return _sign


@pytest.fixture
def db_session():
    """Create a test database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def sample_agent(db_session):
    """Create a sample agent for testing."""
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
def sample_order(db_session, sample_agent):
    """Create a sample order for testing (agent has owner — auth required)."""
    order = Listing(
        order_id="test-order-1",
        agent_id=sample_agent.agent_id,
        order_maker="http://localhost:8001/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "USDC"}}],
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


@pytest.fixture
def sample_agent_no_owner(db_session):
    """Create a sample agent with no owner (auth not required)."""
    agent = Agent(
        id=2,
        agent_id="eip155:31337:0x21df544947ba3e8b3c32561399e88b52dc8b2823:2",
        chain_id=31337,
        identity_registry="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        onchain_agent_id=2,
        registry_address="0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        owner=None,
        token_uri="http://localhost:8002/.well-known/agent-card.json",
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


@pytest.fixture
def sample_order_no_owner(db_session, sample_agent_no_owner):
    """Create a sample order for an agent with no owner (auth not required)."""
    order = Listing(
        order_id="test-order-no-owner",
        agent_id=sample_agent_no_owner.agent_id,
        order_maker="http://localhost:8002/.well-known/agent-card.json",
        offer_resource={"gpu_model": "A100", "region": "us-west"},
        accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "USDC"}}],
        max_duration_seconds=12960000,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order

