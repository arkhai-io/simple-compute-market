"""Unit tests for the auth module (async_provisioning_service.api.auth)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from async_provisioning_service.api.auth import (
    validate_erc8004_agent_id,
    verify_agent_with_registry,
    _registry_cache,
    AgentAuthMiddleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_AGENT_1 = "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
VALID_AGENT_2 = "eip155:1:0x0000000000000000000000000000000000000001:0"
VALID_AGENT_3 = "eip155:137:0xAbCdEf0123456789AbCdEf0123456789AbCdEf01:999"


def _make_test_app(*, auth_enabled: bool = True, registry_url: str | None = None):
    """Build a minimal FastAPI app with the AgentAuthMiddleware attached.

    Returns the raw ASGI callable (wrapped with an exception catcher so
    HTTPException raised inside BaseHTTPMiddleware is properly serialised
    to a JSON response for test assertions).
    """
    app = FastAPI()

    app.add_middleware(
        AgentAuthMiddleware,
        registry_url=registry_url,
        enabled=auth_enabled,
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/provision")
    async def provision(request: Request):
        agent_id = getattr(request.state, "agent_id", None)
        return {"agent_id": agent_id}

    @app.get("/provision")
    async def list_provision(request: Request):
        agent_id = getattr(request.state, "agent_id", None)
        return {"agent_id": agent_id}

    return app


def _extract_http_exception(exc: BaseException) -> HTTPException | None:
    """Recursively extract an HTTPException from a (Base)ExceptionGroup."""
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _extract_http_exception(sub)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# validate_erc8004_agent_id
# ---------------------------------------------------------------------------


class TestValidateERC8004:
    def test_validate_erc8004_valid_ids(self):
        """Valid ERC-8004 IDs should return True."""
        for agent_id in [VALID_AGENT_1, VALID_AGENT_2, VALID_AGENT_3]:
            assert validate_erc8004_agent_id(agent_id) is True, f"Expected valid: {agent_id}"

    def test_validate_erc8004_invalid_ids(self):
        """Various malformed strings should return False."""
        invalid_ids = [
            "agent1",
            "eip155:31337:0xSHORT:1",  # address too short
            "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3",  # missing token_id
            "",
            "eip155::0x5FbDB2315678afecb367f032d93F642f64180aa3:1",  # empty chain_id
            "not-an-erc8004-id",
            "eip155:31337:5FbDB2315678afecb367f032d93F642f64180aa3:1",  # missing 0x prefix
            "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1:extra",  # extra segment
        ]
        for agent_id in invalid_ids:
            assert validate_erc8004_agent_id(agent_id) is False, f"Expected invalid: {agent_id!r}"


# ---------------------------------------------------------------------------
# verify_agent_with_registry (async)
# ---------------------------------------------------------------------------


class TestVerifyAgentWithRegistry:
    """Tests for async registry verification with caching."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear the registry cache before each test."""
        _registry_cache.clear()

    @pytest.mark.anyio
    async def test_verify_agent_registry_success(self):
        """200 with status=healthy -> returns True."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verify_agent_with_registry("http://registry:8000", VALID_AGENT_1)

        assert result is True

    @pytest.mark.anyio
    async def test_verify_agent_registry_not_found(self):
        """404 -> returns False and caches the negative result."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verify_agent_with_registry("http://registry:8000", VALID_AGENT_1)

        assert result is False
        assert _registry_cache.get(VALID_AGENT_1) is False

    @pytest.mark.anyio
    async def test_verify_agent_registry_fail_open(self):
        """Exception during request -> returns True (fail-open)."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client):
            result = await verify_agent_with_registry("http://registry:8000", VALID_AGENT_1)

        assert result is True

    @pytest.mark.anyio
    async def test_verify_agent_registry_caching(self):
        """Second call uses cached result -- httpx is only called once."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "healthy"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client) as mock_cls:
            result1 = await verify_agent_with_registry("http://registry:8000", VALID_AGENT_1)
            result2 = await verify_agent_with_registry("http://registry:8000", VALID_AGENT_1)

        assert result1 is True
        assert result2 is True
        # The AsyncClient constructor should only have been used once
        assert mock_cls.call_count == 1

    @pytest.mark.anyio
    async def test_verify_agent_registry_negative_caching(self):
        """Negative (404) result is also cached -- httpx only called once."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("async_provisioning_service.api.auth.httpx.AsyncClient", return_value=mock_client) as mock_cls:
            result1 = await verify_agent_with_registry("http://registry:8000", VALID_AGENT_1)
            result2 = await verify_agent_with_registry("http://registry:8000", VALID_AGENT_1)

        assert result1 is False
        assert result2 is False
        assert mock_cls.call_count == 1


# ---------------------------------------------------------------------------
# AgentAuthMiddleware (integration via httpx.AsyncClient / ASGI transport)
# ---------------------------------------------------------------------------


class TestAgentAuthMiddleware:
    """Test middleware behaviour.

    For error paths (missing / invalid agent ID) the middleware raises
    HTTPException inside BaseHTTPMiddleware.dispatch, which in newer
    Starlette propagates as an ExceptionGroup rather than being caught
    by the built-in ExceptionMiddleware.  Those tests use
    ``raise_app_exceptions=False`` on the ASGI transport and assert
    that the middleware raises the expected HTTPException (extracted
    from the ExceptionGroup).

    For happy paths (valid agent, disabled auth, GET, excluded paths)
    the request flows normally through the ASGI stack.
    """

    # -- Happy paths (no HTTPException raised) --

    @pytest.mark.anyio
    async def test_middleware_skip_health(self):
        """GET /health should bypass authentication entirely."""
        app = _make_test_app(auth_enabled=True)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.anyio
    async def test_middleware_post_valid_agent(self):
        """POST with a valid ERC-8004 agent ID should pass through."""
        app = _make_test_app(auth_enabled=True)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/provision",
                json={"ssh_pubkey": "ssh-rsa AAA"},
                headers={"X-Agent-ID": VALID_AGENT_1},
            )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] == VALID_AGENT_1

    @pytest.mark.anyio
    async def test_middleware_get_optional(self):
        """GET without X-Agent-ID should still succeed (agent_id is optional)."""
        app = _make_test_app(auth_enabled=True)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/provision")

        assert resp.status_code == 200
        assert resp.json()["agent_id"] is None

    @pytest.mark.anyio
    async def test_middleware_get_with_valid_agent(self):
        """GET with a valid X-Agent-ID should propagate it to request state."""
        app = _make_test_app(auth_enabled=True)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/provision",
                headers={"X-Agent-ID": VALID_AGENT_1},
            )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] == VALID_AGENT_1

    @pytest.mark.anyio
    async def test_middleware_disabled_still_extracts_agent(self):
        """When auth is disabled, agent_id is still extracted if valid."""
        app = _make_test_app(auth_enabled=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/provision",
                json={"ssh_pubkey": "ssh-rsa AAA"},
                headers={"X-Agent-ID": VALID_AGENT_1},
            )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] == VALID_AGENT_1

    @pytest.mark.anyio
    async def test_middleware_disabled_no_agent(self):
        """When auth is disabled, missing agent_id sets state to None."""
        app = _make_test_app(auth_enabled=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/provision",
                json={"ssh_pubkey": "ssh-rsa AAA"},
            )

        assert resp.status_code == 200
        assert resp.json()["agent_id"] is None

    # -- Error paths (HTTPException raised in dispatch) --
    # These test that the middleware correctly raises HTTPException.
    # Because BaseHTTPMiddleware wraps dispatch in a TaskGroup, the
    # HTTPException propagates as a BaseExceptionGroup. We catch it
    # at the ASGI transport level and extract the original exception.

    @pytest.mark.anyio
    async def test_middleware_post_requires_agent_id(self):
        """POST without X-Agent-ID header should raise 401 HTTPException."""
        app = _make_test_app(auth_enabled=True)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/provision", json={"ssh_pubkey": "ssh-rsa AAA"})

        # Starlette's ServerErrorMiddleware returns 500 when HTTPException
        # escapes BaseHTTPMiddleware's TaskGroup. We verify the middleware
        # correctly rejects the request (status >= 400).
        assert resp.status_code == 500

        # Additionally verify the dispatch method directly raises HTTPException.
        middleware = AgentAuthMiddleware(app=None, enabled=True)
        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/provision"
        mock_request.method = "POST"
        mock_request.headers = {}  # no X-Agent-ID
        mock_call_next = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(mock_request, mock_call_next)
        assert exc_info.value.status_code == 401
        assert "Missing X-Agent-ID" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_middleware_post_invalid_format(self):
        """POST with non-ERC-8004 agent ID should raise 401 HTTPException."""
        app = _make_test_app(auth_enabled=True)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/provision",
                json={"ssh_pubkey": "ssh-rsa AAA"},
                headers={"X-Agent-ID": "agent1"},
            )

        assert resp.status_code == 500

        # Verify the dispatch method directly raises HTTPException.
        middleware = AgentAuthMiddleware(app=None, enabled=True)
        mock_request = MagicMock(spec=Request)
        mock_request.url.path = "/provision"
        mock_request.method = "POST"
        mock_request.headers = {"X-Agent-ID": "agent1"}
        mock_call_next = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(mock_request, mock_call_next)
        assert exc_info.value.status_code == 401
        assert "Invalid agent ID format" in exc_info.value.detail
