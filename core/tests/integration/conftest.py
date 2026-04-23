"""
Integration test fixtures for the agent client.

Builds a minimal Starlette application containing only the three Arkhai-specific
route handlers — no ADK, no root_agent, no blockchain, no SQLite.

The key test seam is ``ENABLE_EVENT_QUEUE=true``: when set, all three handlers
take a fast path that calls ``queue_event()`` and returns immediately without
invoking the ADK Runner or root_agent.  This lets us test the full HTTP
plumbing, request validation, and response shape without any AI infrastructure.

``configure_default_ingestion`` is called in the fixture to initialise the
module-level singleton that ``queue_event`` delegates to.  This is the same
call that ``agent.py`` makes at module level, but here we control the parameters
and can inspect the resulting queue.

Testability limitation
----------------------
The handlers (``handle_resource_alert``, ``create_market_order_endpoint``,
``close_market_order_endpoint``) live inside ``core/agent/app/agent.py``, which
runs substantial module-level code (ADK agent construction, blockchain config,
``configure_default_ingestion``) when imported.  We import only the handler
functions themselves after setting environment variables to satisfy the module's
dependencies, then register them on a fresh Starlette app.

TODO(agent-testability): Refactor the three handler functions out of agent.py
into a dedicated ``core/agent/app/routes/`` package so they can be imported
and tested without triggering the full module-level agent initialisation.
This would eliminate the need for environment variable patching in the
conftest and make the handlers independently unit-testable.
"""

from __future__ import annotations

import os
import sys
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.routing import Route


# ---------------------------------------------------------------------------
# Environment setup — must happen before agent.py is imported
# ---------------------------------------------------------------------------

# Minimal env vars to satisfy agent.py module-level code without real services.
_AGENT_ENV = {
    "AGENT_ID": "test_agent",
    "AGENT_DB_PATH": ":memory:",
    "CHAIN_NAME": "anvil",
    "CHAIN_RPC_URL": "http://localhost:8545",
    "REGISTRY_URL": "http://localhost:8080",
    "IDENTITY_REGISTRY_ADDRESS": "0x0000000000000000000000000000000000000000",
    "PROVISIONING_SERVICE_URL": "http://localhost:8081",
    "ENABLE_EVENT_QUEUE": "true",   # ← the critical test seam
    "AGENT_WALLET_ADDRESS": "",     # skip auth checks
    "BASE_URL": "http://localhost:8001",
    "PORT": "8001",
    "TOKEN_REGISTRY_PATH": str(
        __import__("pathlib").Path(__file__).parents[2]
        / "agent/app/data/token_registry_docker_compose.json"
    ),
}


@pytest.fixture(scope="session", autouse=True)
def _agent_env():
    """Patch environment variables before any agent module is imported."""
    original = {k: os.environ.get(k) for k in _AGENT_ENV}
    os.environ.update(_AGENT_ENV)
    yield
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def agent_app_client() -> AsyncIterator[AsyncClient]:
    """Yield an httpx.AsyncClient against a minimal Starlette app.

    Only the three Arkhai-specific routes are registered.  The event queue
    is configured with ``enable_event_queue=True`` so handlers return
    immediately without invoking the ADK runner.
    """
    # Import handler functions after env is set.
    # agent.py module-level code runs here; the env vars above keep it safe.
    from core.agent.app.utils.event_ingestion import configure_default_ingestion
    from core.agent.app.agent import (
        handle_resource_alert,
        create_market_order_endpoint,
        close_market_order_endpoint,
        serve_erc8004_registration_file,
    )

    # Re-initialise ingestion with event queue enabled for this test session.
    configure_default_ingestion(
        event_validation_mode="strict",
        enable_event_queue=True,
        enable_redis_ingest=False,
        redis_url="",
        redis_channels="",
    )

    app = Starlette(
        routes=[
            Route("/alerts/resource", handle_resource_alert, methods=["POST"]),
            Route("/orders/create", create_market_order_endpoint, methods=["POST"]),
            Route("/orders/close", close_market_order_endpoint, methods=["POST"]),
            Route(
                "/.well-known/erc-8004-registration.json",
                serve_erc8004_registration_file,
                methods=["GET"],
            ),
        ]
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client