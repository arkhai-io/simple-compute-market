"""Integration tests for the system diagnostics endpoints."""

from __future__ import annotations

import pytest

from registry_client import RegistryClient, RegistryClientError
from registry_client.models import HealthResponse, SystemStatsResponse


class TestHealth:
    async def test_returns_ok_status(self, registry_client):
        health = await registry_client.get_health()
        assert isinstance(health, HealthResponse)
        assert health.status in ("ok", "healthy")

    async def test_checks_field_present_and_database_ok(self, registry_client):
        health = await registry_client.get_health()
        assert health.extra.get("checks", {}).get("database") == "ok"

    async def test_503_raises_registry_client_error(self, db_session):
        from unittest.mock import MagicMock
        from src.main import app
        from src.db.database import get_db

        def _broken_db():
            mock_session = MagicMock()
            mock_session.execute.side_effect = Exception("disk I/O error")
            try:
                yield mock_session
            finally:
                pass

        import httpx
        app.dependency_overrides[get_db] = _broken_db
        try:
            async with RegistryClient(
                "http://test", transport=httpx.ASGITransport(app=app)
            ) as client:
                with pytest.raises(RegistryClientError) as exc_info:
                    await client.get_health()
            assert exc_info.value.status_code == 503
            assert "degraded" in exc_info.value.body
        finally:
            app.dependency_overrides.clear()


class TestSystemStats:
    async def test_empty_db_returns_zero_counts(self, registry_client):
        stats = await registry_client.get_system_stats()
        assert isinstance(stats, SystemStatsResponse)
        assert stats.publisher_count == 0
        assert stats.order_count == 0

    async def test_publisher_count_reflects_fixtures(
        self, registry_client, maker_publisher, taker_publisher
    ):
        stats = await registry_client.get_system_stats()
        assert stats.publisher_count == 2

    async def test_order_counts_by_status(
        self, registry_client, open_order, authenticated_open_order
    ):
        stats = await registry_client.get_system_stats()
        assert stats.order_count == 2
        assert stats.orders_by_status.get("open") == 2
        assert stats.orders_by_status.get("closed", 0) == 0

    async def test_closed_order_counted(self, registry_client, db_session, maker_publisher):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            listing_id="stats-closed-1",
            publisher_id=maker_publisher.publisher_id,
            offer_resource={"gpu_model": "A100"},
            accepted_escrows=[{"chain_name": "anvil", "escrow_address": "0x" + "11" * 20, "literal_fields": {"token": "USDC"}}],
            max_duration_seconds=3600,
            status=OrderStatusEnum.closed,
        ))
        db_session.commit()
        stats = await registry_client.get_system_stats()
        assert stats.orders_by_status.get("closed") == 1
