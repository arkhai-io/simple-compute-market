"""Pytest configuration and fixtures."""

import time
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.database import Base


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

