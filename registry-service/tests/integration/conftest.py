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

MAKER_PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
MAKER_ADDRESS     = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"

TAKER_PRIVATE_KEY = "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"
TAKER_ADDRESS     = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"


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


def _make_publisher(db_session, identifier: str, storefront_url: str):
    """Create a Publisher with a single eip191 identity."""
    from src.db.models import Publisher, PublisherIdentity
    publisher = Publisher(storefront_url=storefront_url)
    publisher.identities.append(
        PublisherIdentity(scheme="eip191", identifier=identifier.lower())
    )
    db_session.add(publisher)
    db_session.commit()
    db_session.refresh(publisher)
    return publisher


@pytest.fixture
def maker_publisher(db_session):
    return _make_publisher(db_session, MAKER_ADDRESS, "http://localhost:8001/")


@pytest.fixture
def taker_publisher(db_session):
    return _make_publisher(db_session, TAKER_ADDRESS, "http://localhost:8003/")


@pytest.fixture
def open_order(db_session, maker_publisher):
    from src.db.models import Listing, OrderStatusEnum
    order = Listing(
        listing_id="integ-open-order-1",
        publisher_id=maker_publisher.publisher_id,
        offer_resource={"gpu_model": "A100", "region": "us-west", "quantity": 1, "sla": 99.0},
        accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "USDC"}}],
        max_duration_seconds=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order


@pytest.fixture
def authenticated_open_order(db_session, maker_publisher):
    from src.db.models import Listing, OrderStatusEnum
    order = Listing(
        listing_id="integ-auth-order-1",
        publisher_id=maker_publisher.publisher_id,
        offer_resource={"gpu_model": "A100", "region": "us-west", "quantity": 1, "sla": 99.0},
        accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "USDC"}}],
        max_duration_seconds=3600,
        status=OrderStatusEnum.open,
    )
    db_session.add(order)
    db_session.commit()
    db_session.refresh(order)
    return order
