"""Shared pytest fixtures for unit tests."""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from async_provisioning_service.db.models import Base, Credential, CredentialRole, JobStatus, ProvisioningJob

AGENT_1 = "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
AGENT_2 = "eip155:31337:0x70997970C51812dc3A010C7d01b50e0d17dc79C8:2"


@pytest.fixture()
def db_session():
    """In-memory SQLite database session for tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
