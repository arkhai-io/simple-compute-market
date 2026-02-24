"""Unit tests for the auth module (async_provisioning_service.api.auth)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
from fastapi import FastAPI, Request

from async_provisioning_service.api.auth import (
    validate_erc8004_agent_id,
    verify_agent_with_registry,
    _registry_cache,
    AgentAuthMiddleware,
)

VALID_AGENT_1 = "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
VALID_AGENT_2 = "eip155:1:0x0000000000000000000000000000000000000001:0"
VALID_AGENT_3 = "eip155:137:0xAbCdEf0123456789AbCdEf0123456789AbCdEf01:999"

REGISTRY_URL = "http://registry:8000"


def _make_mock_client(*, response=None, side_effect=None):
    """Build a mock httpx.AsyncClient usable as an async context manager."""
    client = AsyncMock()
    if side_effect:
        client.get = AsyncMock(side_effect=side_effect)
    else:
        client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _make_test_app(*, auth_enabled: bool = True, registry_url: str | None = None):
    """Build a minimal FastAPI app with the AgentAuthMiddleware attached."""
    app = FastAPI()
    app.add_middleware(
        AgentAuthMiddleware,
        registry_url=registry_url,
        enabled=auth_enabled,
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/v1/jobs")
    async def provision(request: Request):
        agent_id = getattr(request.state, "agent_id", None)
        return {"agent_id": agent_id}

    @app.get("/api/v1/jobs")
    async def list_provision(request: Request):
        agent_id = getattr(request.state, "agent_id", None)
        return {"agent_id": agent_id}

    return app


async def _asgi_request(app, method, path, **kwargs):
    """Send a request through the ASGI transport and return the response."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await getattr(client, method)(path, **kwargs)


class TestValidateERC8004:
    def test_validate_erc8004_valid_ids(self):
        """Valid ERC-8004 IDs should return True."""
        for agent_id in [VALID_AGENT_1, VALID_AGENT_2, VALID_AGENT_3]:
            assert validate_erc8004_agent_id(agent_id) is True, f"Expected valid: {agent_id}"

    def test_validate_erc8004_invalid_ids(self):
        """Various malformed strings should return False."""
        invalid_ids = [
            "agent1",
            "eip155:31337:0xSHORT:1",
            "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3",
            "",
            "eip155::0x5FbDB2315678afecb367f032d93F642f64180aa3:1",
            "not-an-erc8004-id",
            "eip155:31337:5FbDB2315678afecb367f032d93F642f64180aa3:1",
            "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1:extra",
        ]
        for agent_id in invalid_ids:
            assert validate_erc8004_agent_id(agent_id) is False, f"Expected invalid: {agent_id!r}"


class TestVerifyAgentWithRegistry:
    """Tests for async registry verification with caching."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _registry_cache.clear()

    @pytest.mark.anyio
    async def test_verify_agent_registry_success(self):
        """200 with status=healthy -> returns True."""
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "healthy"}
        mock_client = _make_mock_client(response=response)

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verify_agent_with_registry(REGISTRY_URL, VALID_AGENT_1)

        assert result is True

    @pytest.mark.anyio
    async def test_verify_agent_registry_not_found(self):
        """404 -> returns False and caches the negative result."""
        response = MagicMock(status_code=404)
        mock_client = _make_mock_client(response=response)

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verify_agent_with_registry(REGISTRY_URL, VALID_AGENT_1)

        assert result is False
        assert _registry_cache.get(VALID_AGENT_1) is False

    @pytest.mark.anyio
    async def test_verify_agent_registry_fail_open(self):
        """Exception during request -> returns True (fail-open)."""
        mock_client = _make_mock_client(side_effect=httpx.ConnectError("connection refused"))

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verify_agent_with_registry(REGISTRY_URL, VALID_AGENT_1)

        assert result is True


class TestAgentAuthMiddleware:

    @pytest.mark.anyio
    async def test_middleware_skip_health(self):
        """GET /health should bypass authentication entirely."""
        resp = await _asgi_request(_make_test_app(auth_enabled=True), "get", "/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.anyio
    async def test_middleware_post_valid_agent(self):
        """POST with a valid ERC-8004 agent ID should pass through."""
        resp = await _asgi_request(
            _make_test_app(auth_enabled=True),
            "post",
            "/api/v1/jobs",
            json={"ssh_pubkey": "ssh-rsa AAA"},
            headers={"X-Agent-ID": VALID_AGENT_1},
        )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] == VALID_AGENT_1

    @pytest.mark.anyio
    async def test_middleware_get_optional(self):
        """GET without X-Agent-ID should still succeed (agent_id is optional)."""
        resp = await _asgi_request(_make_test_app(auth_enabled=True), "get", "/api/v1/jobs")

        assert resp.status_code == 200
        assert resp.json()["agent_id"] is None

    @pytest.mark.anyio
    async def test_middleware_get_with_valid_agent(self):
        """GET with a valid X-Agent-ID should propagate it to request state."""
        resp = await _asgi_request(
            _make_test_app(auth_enabled=True),
            "get",
            "/api/v1/jobs",
            headers={"X-Agent-ID": VALID_AGENT_1},
        )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] == VALID_AGENT_1

    @pytest.mark.anyio
    async def test_middleware_disabled_still_extracts_agent(self):
        """When auth is disabled, agent_id is still extracted if valid."""
        resp = await _asgi_request(
            _make_test_app(auth_enabled=False),
            "post",
            "/api/v1/jobs",
            json={"ssh_pubkey": "ssh-rsa AAA"},
            headers={"X-Agent-ID": VALID_AGENT_1},
        )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] == VALID_AGENT_1

    @pytest.mark.anyio
    async def test_middleware_disabled_no_agent(self):
        """When auth is disabled, missing agent_id sets state to None."""
        resp = await _asgi_request(
            _make_test_app(auth_enabled=False),
            "post",
            "/api/v1/jobs",
            json={"ssh_pubkey": "ssh-rsa AAA"},
        )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] is None

    @pytest.mark.anyio
    async def test_middleware_post_requires_agent_id(self):
        """POST without X-Agent-ID header should return 401."""
        resp = await _asgi_request(
            _make_test_app(auth_enabled=True),
            "post",
            "/api/v1/jobs",
            json={"ssh_pubkey": "ssh-rsa AAA"},
        )

        assert resp.status_code == 401
        assert "Missing X-Agent-ID" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_middleware_post_invalid_format(self):
        """POST with non-ERC-8004 agent ID should return 401."""
        resp = await _asgi_request(
            _make_test_app(auth_enabled=True),
            "post",
            "/api/v1/jobs",
            json={"ssh_pubkey": "ssh-rsa AAA"},
            headers={"X-Agent-ID": "agent1"},
        )

        assert resp.status_code == 401
        assert "Invalid agent ID format" in resp.json()["detail"]
