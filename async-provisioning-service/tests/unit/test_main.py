"""Unit tests for async_provisioning_service.main."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from async_provisioning_service.api.auth import AgentAuthMiddleware
from async_provisioning_service.api.rate_limit import AgentRateLimitMiddleware
from async_provisioning_service.db.database import get_db
from async_provisioning_service.main import app, lifespan


class TestAppStructure:
    def test_cors_middleware_present(self):
        middleware_classes = [m.cls for m in app.user_middleware]
        assert CORSMiddleware in middleware_classes

    def test_auth_middleware_wired(self):
        middleware_classes = [m.cls for m in app.user_middleware]
        assert AgentAuthMiddleware in middleware_classes

    def test_rate_limit_middleware_wired(self):
        middleware_classes = [m.cls for m in app.user_middleware]
        assert AgentRateLimitMiddleware in middleware_classes

    def test_routes_include_api_v1_prefix(self):
        paths = [route.path for route in app.routes]
        assert any(path.startswith("/api/v1") for path in paths)


class TestLifespan:
    @pytest.mark.anyio
    async def test_lifespan_calls_init_db(self):
        with patch("async_provisioning_service.main.init_db") as mock_init_db:
            async with lifespan(FastAPI()):
                pass

        mock_init_db.assert_called_once()


class TestHealthRoute:
    @pytest.mark.anyio
    async def test_health_route_accessible(self):
        mock_db = MagicMock()
        mock_db.execute.return_value = None

        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            with patch("async_provisioning_service.main.init_db"):
                with patch(
                    "async_provisioning_service.api.routes.get_redis",
                    AsyncMock(return_value=mock_redis),
                ):
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(
                        transport=transport, base_url="http://test"
                    ) as client:
                        resp = await client.get("/health")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200


class TestDatabase:
    """Coverage for db/database.py get_db and init_db."""

    def test_get_db_yields_session_and_closes(self):
        """get_db yields a session then closes it on exit."""
        with patch("async_provisioning_service.db.database.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            from async_provisioning_service.db.database import get_db as _get_db
            gen = _get_db()
            db = next(gen)
            assert db is mock_session

            try:
                next(gen)
            except StopIteration:
                pass

            mock_session.close.assert_called_once()

    def test_init_db_creates_tables(self):
        """init_db calls Base.metadata.create_all."""
        with patch("async_provisioning_service.db.database.Base") as mock_base:
            from async_provisioning_service.db.database import init_db as _init_db
            _init_db()
        mock_base.metadata.create_all.assert_called_once()
