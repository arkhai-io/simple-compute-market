"""Unit tests for the rate limiting module (async_provisioning_service.api.rate_limit)."""

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI, Request

from async_provisioning_service.api.auth import AgentAuthMiddleware
from async_provisioning_service.api.rate_limit import AgentRateLimitMiddleware, SlidingWindowCounter

AGENT_1 = "eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1"
AGENT_2 = "eip155:31337:0x70997970C51812dc3A010C7d01b50e0d17dc79C8:2"


def _make_rate_limit_app(*, enabled: bool = True, max_requests: int = 3):
    """Build a minimal FastAPI app with auth (disabled) + rate limit middleware.

    Middleware is added in LIFO order: AgentRateLimitMiddleware first so auth
    (AgentAuthMiddleware) executes outermost and sets request.state.agent_id
    before the rate limiter inspects it.
    """
    app = FastAPI()

    # Add rate limit first (runs inner / second)
    app.add_middleware(AgentRateLimitMiddleware, enabled=enabled, max_requests=max_requests)
    # Add auth second (runs outer / first) — disabled so it passes X-Agent-ID through
    app.add_middleware(AgentAuthMiddleware, enabled=False)

    @app.post("/api/v1/jobs")
    async def post_endpoint(request: Request):
        return {"agent_id": getattr(request.state, "agent_id", None)}

    @app.get("/api/v1/jobs")
    async def get_endpoint(request: Request):
        return {"agent_id": getattr(request.state, "agent_id", None)}

    return app


async def _post(client: httpx.AsyncClient, headers: dict | None = None) -> httpx.Response:
    return await client.post("/api/v1/jobs", json={}, headers=headers or {})


async def _get(client: httpx.AsyncClient, headers: dict | None = None) -> httpx.Response:
    return await client.get("/api/v1/jobs", headers=headers or {})


class TestSlidingWindowCounter:
    def test_allows_within_limit(self):
        counter = SlidingWindowCounter(max_requests=3)
        assert counter.is_allowed("agent-a") is True
        assert counter.is_allowed("agent-a") is True
        assert counter.is_allowed("agent-a") is True

    def test_blocks_at_limit(self):
        counter = SlidingWindowCounter(max_requests=3)
        counter.is_allowed("agent-a")
        counter.is_allowed("agent-a")
        counter.is_allowed("agent-a")
        # 4th request exceeds max=3
        assert counter.is_allowed("agent-a") is False

    def test_expires_old_timestamps(self):
        counter = SlidingWindowCounter(max_requests=3, window_seconds=60)
        base_time = 1000.0

        # Record 3 requests at t=1000
        with patch("time.monotonic", return_value=base_time):
            counter.is_allowed("agent-a")
            counter.is_allowed("agent-a")
            counter.is_allowed("agent-a")

        # Advance time by 70 seconds — old timestamps fall outside the 60s window
        advanced_time = base_time + 70.0
        with patch("time.monotonic", return_value=advanced_time):
            # All old entries should be cleaned; this new request should be allowed
            assert counter.is_allowed("agent-a") is True

    def test_remaining_decrements(self):
        counter = SlidingWindowCounter(max_requests=3)
        assert counter.remaining("agent-a") == 3

        counter.is_allowed("agent-a")
        assert counter.remaining("agent-a") == 2

        counter.is_allowed("agent-a")
        assert counter.remaining("agent-a") == 1

        counter.is_allowed("agent-a")
        assert counter.remaining("agent-a") == 0


class TestAgentRateLimitMiddleware:
    @pytest.mark.anyio
    async def test_disabled_passes_all(self):
        app = _make_rate_limit_app(enabled=False, max_requests=1)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(10):
                resp = await _post(client, headers={"X-Agent-ID": AGENT_1})
                assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_get_bypasses_limit(self):
        app = _make_rate_limit_app(enabled=True, max_requests=1)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(5):
                resp = await _get(client, headers={"X-Agent-ID": AGENT_1})
                assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_missing_agent_id_bypasses(self):
        # With no X-Agent-ID, auth middleware sets agent_id=None.
        # Rate limiter skips requests with no agent_id.
        app = _make_rate_limit_app(enabled=True, max_requests=1)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(5):
                resp = await _post(client)
                assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_post_rate_limited_returns_429(self):
        # Note: raise HTTPException inside BaseHTTPMiddleware propagates through
        # ServerErrorMiddleware to the test client as an exception rather than
        # a response body. We verify the status code via exc.status_code.
        from fastapi import HTTPException as FastAPIHTTPException

        app = _make_rate_limit_app(enabled=True, max_requests=2)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # First two allowed
            resp1 = await _post(client, headers={"X-Agent-ID": AGENT_1})
            assert resp1.status_code == 200
            resp2 = await _post(client, headers={"X-Agent-ID": AGENT_1})
            assert resp2.status_code == 200
            # Third is rate limited — HTTPException propagates through ASGI transport
            with pytest.raises(FastAPIHTTPException) as exc_info:
                await _post(client, headers={"X-Agent-ID": AGENT_1})
        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        assert "Retry-After" in exc_info.value.headers

    @pytest.mark.anyio
    async def test_remaining_header_on_success(self):
        app = _make_rate_limit_app(enabled=True, max_requests=5)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await _post(client, headers={"X-Agent-ID": AGENT_1})
            assert resp.status_code == 200
            assert "X-RateLimit-Remaining" in resp.headers
            assert int(resp.headers["X-RateLimit-Remaining"]) >= 0

    @pytest.mark.anyio
    async def test_multiple_agents_independent(self):
        from fastapi import HTTPException as FastAPIHTTPException

        app = _make_rate_limit_app(enabled=True, max_requests=1)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Exhaust AGENT_1's quota
            resp1 = await _post(client, headers={"X-Agent-ID": AGENT_1})
            assert resp1.status_code == 200

            with pytest.raises(FastAPIHTTPException) as exc_info:
                await _post(client, headers={"X-Agent-ID": AGENT_1})
            assert exc_info.value.status_code == 429

            # AGENT_2 should still be allowed
            resp2 = await _post(client, headers={"X-Agent-ID": AGENT_2})
            assert resp2.status_code == 200
