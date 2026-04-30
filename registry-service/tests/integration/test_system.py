"""Integration tests for the system diagnostics endpoints."""

from __future__ import annotations

import pytest

from registry_client import RegistryClient, RegistryClientError
from registry_client.models import HealthResponse, SystemConfigResponse, SystemSyncResponse, SystemStatsResponse
from tests.integration.conftest import IDENTITY_REGISTRY


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


class TestSystemConfig:
    async def test_returns_chain_id_and_contract_addresses(self, registry_client):
        config = await registry_client.get_system_config()
        assert isinstance(config, SystemConfigResponse)
        assert isinstance(config.chain_id, int)
        for field in (
            "identity_registry_address",
            "reputation_registry_address",
            "validation_registry_address",
        ):
            addr = getattr(config, field)
            assert addr.startswith("0x"), f"{field} not an address: {addr!r}"

    async def test_rpc_url_non_empty(self, registry_client):
        config = await registry_client.get_system_config()
        assert config.rpc_url

    async def test_heartbeat_ttl_positive(self, registry_client):
        config = await registry_client.get_system_config()
        assert isinstance(config.heartbeat_ttl_secs, int)
        assert config.heartbeat_ttl_secs > 0


class TestSystemSync:
    async def test_event_sync_shape(self, registry_client):
        sync = await registry_client.get_system_sync()
        assert isinstance(sync, SystemSyncResponse)
        assert isinstance(sync.event_sync_running, bool)
        assert isinstance(sync.event_sync_last_block, int)

    async def test_health_check_shape(self, registry_client):
        sync = await registry_client.get_system_sync()
        assert isinstance(sync.health_check_running, bool)
        assert isinstance(sync.health_check_enabled, bool)

    async def test_event_sync_not_running_outside_lifespan(self, registry_client):
        sync = await registry_client.get_system_sync()
        assert sync.event_sync_running is False
        assert sync.event_sync_last_block == 0


class TestSystemStats:
    async def test_empty_db_returns_zero_counts(self, registry_client):
        stats = await registry_client.get_system_stats()
        assert isinstance(stats, SystemStatsResponse)
        assert stats.agent_count == 0
        assert stats.order_count == 0

    async def test_agent_count_reflects_fixtures(
        self, registry_client, agent_no_owner, maker_agent
    ):
        stats = await registry_client.get_system_stats()
        assert stats.agent_count == 2

    async def test_order_counts_by_status(
        self, registry_client, open_order, authenticated_open_order
    ):
        stats = await registry_client.get_system_stats()
        assert stats.order_count == 2
        assert stats.orders_by_status.get("open") == 2
        assert stats.orders_by_status.get("closed", 0) == 0

    async def test_closed_order_counted(self, registry_client, db_session, agent_no_owner):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            listing_id="stats-closed-1",
            agent_id=agent_no_owner.agent_id,
            seller=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            max_duration_seconds=3600,
            status=OrderStatusEnum.closed,
        ))
        db_session.commit()
        stats = await registry_client.get_system_stats()
        assert stats.orders_by_status.get("closed") == 1


class TestAttestationStats:
    """Semantic tests for GET /api/v1/system/stats/attestations.

    Each test builds a precise DB state and asserts the counts returned
    match exactly — verifying that the three counters are independent and
    that the 'settled' count correctly requires both attestations.
    """

    async def test_empty_db_returns_zero_counts(self, registry_client):
        stats = await registry_client.get_attestation_stats()
        assert stats.settled_listing_count == 0
        assert stats.seller_attestation_count == 0
        assert stats.buyer_attestation_count == 0

    async def test_order_with_no_attestations_not_counted(
        self, registry_client, open_order
    ):
        stats = await registry_client.get_attestation_stats()
        assert stats.settled_listing_count == 0
        assert stats.seller_attestation_count == 0
        assert stats.buyer_attestation_count == 0

    async def test_only_maker_attestation_counted_separately(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            listing_id="attest-maker-only-1",
            agent_id=agent_no_owner.agent_id,
            seller=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            max_duration_seconds=3600,
            status=OrderStatusEnum.accepted,
            seller_attestation="0xmaker_uid_abc",
            buyer_attestation=None,
        ))
        db_session.commit()
        stats = await registry_client.get_attestation_stats()
        assert stats.seller_attestation_count == 1
        assert stats.buyer_attestation_count == 0
        assert stats.settled_listing_count == 0

    async def test_only_taker_attestation_counted_separately(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            listing_id="attest-taker-only-1",
            agent_id=agent_no_owner.agent_id,
            seller=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            max_duration_seconds=3600,
            status=OrderStatusEnum.accepted,
            seller_attestation=None,
            buyer_attestation="0xtaker_uid_xyz",
        ))
        db_session.commit()
        stats = await registry_client.get_attestation_stats()
        assert stats.seller_attestation_count == 0
        assert stats.buyer_attestation_count == 1
        assert stats.settled_listing_count == 0

    async def test_both_attestations_counted_as_settled(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            listing_id="attest-settled-1",
            agent_id=agent_no_owner.agent_id,
            seller=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            max_duration_seconds=3600,
            status=OrderStatusEnum.closed,
            seller_attestation="0xmaker_uid_001",
            buyer_attestation="0xtaker_uid_001",
        ))
        db_session.commit()
        stats = await registry_client.get_attestation_stats()
        assert stats.seller_attestation_count == 1
        assert stats.buyer_attestation_count == 1
        assert stats.settled_listing_count == 1

    async def test_mixed_orders_counted_independently(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        agent_id = agent_no_owner.agent_id
        maker = agent_no_owner.token_uri
        db_session.add_all([
            Listing(
                listing_id="mix-open", agent_id=agent_id, seller=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                max_duration_seconds=3600, status=OrderStatusEnum.open,
                seller_attestation=None, buyer_attestation=None,
            ),
            Listing(
                listing_id="mix-maker-only", agent_id=agent_id, seller=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                max_duration_seconds=3600, status=OrderStatusEnum.accepted,
                seller_attestation="0xmaker_mix_001", buyer_attestation=None,
            ),
            Listing(
                listing_id="mix-settled", agent_id=agent_id, seller=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                max_duration_seconds=3600, status=OrderStatusEnum.closed,
                seller_attestation="0xmaker_mix_002", buyer_attestation="0xtaker_mix_002",
            ),
        ])
        db_session.commit()
        stats = await registry_client.get_attestation_stats()
        assert stats.seller_attestation_count == 2
        assert stats.buyer_attestation_count == 1
        assert stats.settled_listing_count == 1

    async def test_settled_count_does_not_double_count(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        agent_id = agent_no_owner.agent_id
        maker = agent_no_owner.token_uri
        db_session.add_all([
            Listing(
                listing_id="double-settled-1", agent_id=agent_id, seller=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                max_duration_seconds=3600, status=OrderStatusEnum.closed,
                seller_attestation="0xm1", buyer_attestation="0xt1",
            ),
            Listing(
                listing_id="double-settled-2", agent_id=agent_id, seller=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                max_duration_seconds=3600, status=OrderStatusEnum.closed,
                seller_attestation="0xm2", buyer_attestation="0xt2",
            ),
        ])
        db_session.commit()
        stats = await registry_client.get_attestation_stats()
        assert stats.seller_attestation_count == 2
        assert stats.buyer_attestation_count == 2
        assert stats.settled_listing_count == 2
