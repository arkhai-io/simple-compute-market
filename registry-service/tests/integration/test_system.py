"""Integration tests for the system diagnostics endpoints."""

from __future__ import annotations

import pytest
import httpx

from registry_client import RegistryClient, RegistryClientError
from registry_client.models import HealthResponse
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
        resp = await registry_client._request("GET", "/api/v1/system/config")
        assert isinstance(resp["chain_id"], int)
        for field in (
            "identity_registry_address",
            "reputation_registry_address",
            "validation_registry_address",
        ):
            assert resp[field].startswith("0x"), f"{field} not an address: {resp[field]!r}"

    async def test_rpc_url_non_empty(self, registry_client):
        resp = await registry_client._request("GET", "/api/v1/system/config")
        assert resp.get("rpc_url")

    async def test_heartbeat_ttl_positive(self, registry_client):
        resp = await registry_client._request("GET", "/api/v1/system/config")
        assert isinstance(resp["heartbeat_ttl_secs"], int)
        assert resp["heartbeat_ttl_secs"] > 0


class TestSystemSync:
    async def test_event_sync_shape(self, registry_client):
        resp = await registry_client._request("GET", "/api/v1/system/sync")
        es = resp["event_sync"]
        assert isinstance(es["running"], bool)
        assert isinstance(es["last_synced_block"], int)

    async def test_health_check_shape(self, registry_client):
        resp = await registry_client._request("GET", "/api/v1/system/sync")
        hc = resp["health_check"]
        assert isinstance(hc["running"], bool)
        assert isinstance(hc["enabled"], bool)

    async def test_event_sync_not_running_outside_lifespan(self, registry_client):
        resp = await registry_client._request("GET", "/api/v1/system/sync")
        assert resp["event_sync"]["running"] is False
        assert resp["event_sync"]["last_synced_block"] == 0


class TestSystemStats:
    async def test_empty_db_returns_zero_counts(self, registry_client):
        resp = await registry_client._request("GET", "/api/v1/system/stats")
        assert resp["agent_count"] == 0
        assert resp["order_count"] == 0

    async def test_agent_count_reflects_fixtures(
        self, registry_client, agent_no_owner, maker_agent
    ):
        resp = await registry_client._request("GET", "/api/v1/system/stats")
        assert resp["agent_count"] == 2

    async def test_order_counts_by_status(
        self, registry_client, open_order, authenticated_open_order
    ):
        resp = await registry_client._request("GET", "/api/v1/system/stats")
        assert resp["order_count"] == 2
        assert resp["orders_by_status"]["open"] == 2
        assert resp["orders_by_status"]["closed"] == 0

    async def test_closed_order_counted(self, registry_client, db_session, agent_no_owner):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            order_id="stats-closed-1",
            agent_id=agent_no_owner.agent_id,
            order_maker=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            duration_hours=1,
            status=OrderStatusEnum.closed,
        ))
        db_session.commit()
        resp = await registry_client._request("GET", "/api/v1/system/stats")
        assert resp["orders_by_status"]["closed"] == 1


class TestAttestationStats:
    """Semantic tests for GET /api/v1/system/stats/attestations.

    Each test builds a precise DB state and asserts the counts returned
    match exactly — verifying that the three counters are independent and
    that the 'settled' count correctly requires both attestations.
    """

    async def test_empty_db_returns_zero_counts(self, registry_client):
        stats = await registry_client.get_attestation_stats()
        assert stats.settled_order_count == 0
        assert stats.maker_attestation_count == 0
        assert stats.taker_attestation_count == 0

    async def test_order_with_no_attestations_not_counted(
        self, registry_client, open_order
    ):
        # open_order has neither attestation set
        stats = await registry_client.get_attestation_stats()
        assert stats.settled_order_count == 0
        assert stats.maker_attestation_count == 0
        assert stats.taker_attestation_count == 0

    async def test_only_maker_attestation_counted_separately(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            order_id="attest-maker-only-1",
            agent_id=agent_no_owner.agent_id,
            order_maker=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            duration_hours=1,
            status=OrderStatusEnum.accepted,
            maker_attestation="0xmaker_uid_abc",
            taker_attestation=None,
        ))
        db_session.commit()

        stats = await registry_client.get_attestation_stats()
        assert stats.maker_attestation_count == 1
        assert stats.taker_attestation_count == 0
        # Not settled — taker_attestation is missing
        assert stats.settled_order_count == 0

    async def test_only_taker_attestation_counted_separately(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            order_id="attest-taker-only-1",
            agent_id=agent_no_owner.agent_id,
            order_maker=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            duration_hours=1,
            status=OrderStatusEnum.accepted,
            maker_attestation=None,
            taker_attestation="0xtaker_uid_xyz",
        ))
        db_session.commit()

        stats = await registry_client.get_attestation_stats()
        assert stats.maker_attestation_count == 0
        assert stats.taker_attestation_count == 1
        # Not settled — maker_attestation is missing
        assert stats.settled_order_count == 0

    async def test_both_attestations_counted_as_settled(
        self, registry_client, db_session, agent_no_owner
    ):
        from src.db.models import Listing, OrderStatusEnum
        db_session.add(Listing(
            order_id="attest-settled-1",
            agent_id=agent_no_owner.agent_id,
            order_maker=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            duration_hours=1,
            status=OrderStatusEnum.closed,
            maker_attestation="0xmaker_uid_001",
            taker_attestation="0xtaker_uid_001",
        ))
        db_session.commit()

        stats = await registry_client.get_attestation_stats()
        assert stats.maker_attestation_count == 1
        assert stats.taker_attestation_count == 1
        assert stats.settled_order_count == 1

    async def test_mixed_orders_counted_independently(
        self, registry_client, db_session, agent_no_owner
    ):
        """Three orders in different attestation states — each counter
        reflects only its own condition, settled requires both."""
        from src.db.models import Listing, OrderStatusEnum

        agent_id = agent_no_owner.agent_id
        maker = agent_no_owner.token_uri

        db_session.add_all([
            Listing(
                order_id="mix-open",
                agent_id=agent_id, order_maker=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                duration_hours=1, status=OrderStatusEnum.open,
                maker_attestation=None, taker_attestation=None,
            ),
            Listing(
                order_id="mix-maker-only",
                agent_id=agent_id, order_maker=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                duration_hours=1, status=OrderStatusEnum.accepted,
                maker_attestation="0xmaker_mix_001", taker_attestation=None,
            ),
            Listing(
                order_id="mix-settled",
                agent_id=agent_id, order_maker=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                duration_hours=1, status=OrderStatusEnum.closed,
                maker_attestation="0xmaker_mix_002", taker_attestation="0xtaker_mix_002",
            ),
        ])
        db_session.commit()

        stats = await registry_client.get_attestation_stats()
        assert stats.maker_attestation_count == 2  # maker-only + settled
        assert stats.taker_attestation_count == 1  # settled only
        assert stats.settled_order_count == 1       # only the fully settled one

    async def test_settled_count_does_not_double_count(
        self, registry_client, db_session, agent_no_owner
    ):
        """Two fully settled orders → settled_order_count == 2, not 4."""
        from src.db.models import Listing, OrderStatusEnum

        agent_id = agent_no_owner.agent_id
        maker = agent_no_owner.token_uri

        db_session.add_all([
            Listing(
                order_id="double-settled-1",
                agent_id=agent_id, order_maker=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                duration_hours=1, status=OrderStatusEnum.closed,
                maker_attestation="0xm1", taker_attestation="0xt1",
            ),
            Listing(
                order_id="double-settled-2",
                agent_id=agent_id, order_maker=maker,
                offer_resource={"gpu_model": "A100"}, demand_resource={"token": "USDC"},
                duration_hours=1, status=OrderStatusEnum.closed,
                maker_attestation="0xm2", taker_attestation="0xt2",
            ),
        ])
        db_session.commit()

        stats = await registry_client.get_attestation_stats()
        assert stats.maker_attestation_count == 2
        assert stats.taker_attestation_count == 2
        assert stats.settled_order_count == 2