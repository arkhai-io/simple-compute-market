"""Integration tests for the orders API.

All calls go through async RegistryClient methods.  No route strings in
test code.  RegistryClientError is raised by the client on non-2xx responses.
"""

from __future__ import annotations

import pytest

from registry_client import RegistryClientError
from registry_client.models import OrderListResponse, OrderRequest, OrderSummary
from tests.integration.conftest import MAKER_PRIVATE_KEY, TAKER_PRIVATE_KEY


class TestListOrders:
    async def test_empty_db_returns_empty_list(self, registry_client):
        result = await registry_client.list_orders(status=None)
        assert isinstance(result, OrderListResponse)
        assert result.orders == []

    async def test_open_order_appears_in_default_listing(self, registry_client, open_order):
        result = await registry_client.list_orders()
        ids = [str(o.id) for o in result.orders]
        assert open_order.order_id in ids

    async def test_status_filter_excludes_non_matching(self, registry_client, open_order):
        result = await registry_client.list_orders(status="closed")
        ids = [str(o.id) for o in result.orders]
        assert open_order.order_id not in ids

    async def test_all_items_are_order_summary(self, registry_client, open_order):
        result = await registry_client.list_orders()
        assert all(isinstance(o, OrderSummary) for o in result.orders)

    async def test_order_summary_fields_populated(self, registry_client, open_order):
        result = await registry_client.list_orders()
        order = next(o for o in result.orders if str(o.id) == open_order.order_id)
        assert order.status == "open"
        assert order.maker_agent_id is not None


class TestGetOrder:
    async def test_returns_typed_order_summary(self, registry_client, open_order):
        order = await registry_client.get_order(open_order.order_id)
        assert isinstance(order, OrderSummary)
        assert str(order.id) == open_order.order_id
        assert order.status == "open"

    async def test_404_raises_registry_client_error(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_order("nonexistent-order-id")
        assert exc_info.value.status_code == 404

    async def test_offer_and_demand_populated(self, registry_client, open_order):
        order = await registry_client.get_order(open_order.order_id)
        assert order.offer
        assert order.demand


class TestPublishOrder:
    async def test_unauthenticated_agent_accepts_publish(self, registry_client, agent_no_owner):
        result = await registry_client.publish_order(
            agent_no_owner.agent_id,
            OrderRequest(
                offer={"gpu_model": "A100", "region": "us-west"},
                demand={"token": "USDC", "amount": 100.0},
                duration_hours=1.0,
            ),
            private_key=MAKER_PRIVATE_KEY,
        )
        assert "order_id" in result

    async def test_authenticated_valid_signature_accepted(self, registry_client, maker_agent):
        result = await registry_client.publish_order(
            maker_agent.agent_id,
            OrderRequest(
                offer={"gpu_model": "A100", "region": "us-west"},
                demand={"token": "USDC", "amount": 100.0},
                duration_hours=1.0,
            ),
            private_key=MAKER_PRIVATE_KEY,
        )
        assert "order_id" in result

    async def test_authenticated_wrong_key_raises_401(self, registry_client, maker_agent):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.publish_order(
                maker_agent.agent_id,
                OrderRequest(offer={"gpu_model": "A100"}, demand={"token": "USDC"},
                             duration_hours=1.0),
                private_key=TAKER_PRIVATE_KEY,
            )
        assert exc_info.value.status_code == 401

    async def test_unknown_agent_raises_404(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.publish_order(
                "nonexistent-agent",
                OrderRequest(offer={}, demand={}, duration_hours=1.0),
                private_key=MAKER_PRIVATE_KEY,
            )
        assert exc_info.value.status_code == 404


class TestGetAgentOrders:
    async def test_returns_agent_orders(self, registry_client, open_order, agent_no_owner):
        result = await registry_client.get_agent_orders(agent_no_owner.agent_id)
        assert open_order.order_id in [str(o.id) for o in result.orders]

    async def test_empty_for_agent_with_no_orders(self, registry_client, maker_agent):
        result = await registry_client.get_agent_orders(maker_agent.agent_id)
        assert result.orders == []

    async def test_status_filter(self, registry_client, open_order, agent_no_owner, db_session):
        from src.db.models import MarketOrder, OrderStatusEnum
        db_session.add(MarketOrder(
            order_id="agent-orders-closed",
            agent_id=agent_no_owner.agent_id,
            order_maker=agent_no_owner.token_uri,
            offer_resource={"gpu_model": "A100"},
            demand_resource={"token": "USDC"},
            duration_hours=1,
            status=OrderStatusEnum.closed,
        ))
        db_session.commit()

        open_ids = [str(o.id) for o in
                    (await registry_client.get_agent_orders(agent_no_owner.agent_id,
                                                            status="open")).orders]
        closed_ids = [str(o.id) for o in
                      (await registry_client.get_agent_orders(agent_no_owner.agent_id,
                                                              status="closed")).orders]

        assert open_order.order_id in open_ids
        assert "agent-orders-closed" not in open_ids
        assert "agent-orders-closed" in closed_ids

    async def test_all_items_are_order_summary(self, registry_client, open_order, agent_no_owner):
        result = await registry_client.get_agent_orders(agent_no_owner.agent_id)
        assert all(isinstance(o, OrderSummary) for o in result.orders)


class TestDeleteOrder:
    async def test_unauthenticated_order_deleted(self, registry_client, open_order):
        await registry_client.delete_order(open_order.order_id, private_key=MAKER_PRIVATE_KEY)
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_order(open_order.order_id)
        assert exc_info.value.status_code == 404

    async def test_authenticated_valid_key_deletes(
        self, registry_client, authenticated_open_order
    ):
        await registry_client.delete_order(
            authenticated_open_order.order_id, private_key=MAKER_PRIVATE_KEY
        )
        with pytest.raises(RegistryClientError):
            await registry_client.get_order(authenticated_open_order.order_id)

    async def test_authenticated_wrong_key_raises_401(
        self, registry_client, authenticated_open_order
    ):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.delete_order(
                authenticated_open_order.order_id, private_key=TAKER_PRIVATE_KEY
            )
        assert exc_info.value.status_code == 401

    async def test_nonexistent_raises_404(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.delete_order("does-not-exist", private_key=MAKER_PRIVATE_KEY)
        assert exc_info.value.status_code == 404


class TestOrderLifecycle:
    async def test_publish_list_get_accept_delete(self, registry_client, db_session):
        from src.db.models import Agent

        agent_a = Agent(
            id=20, agent_id="eip155:31337:0xabc:20", chain_id=31337,
            identity_registry="0xabc", onchain_agent_id=20,
            registry_address="0xabc", owner=None,
            token_uri="http://localhost:9001/.well-known/agent-card.json",
        )
        agent_b = Agent(
            id=21, agent_id="eip155:31337:0xabc:21", chain_id=31337,
            identity_registry="0xabc", onchain_agent_id=21,
            registry_address="0xabc", owner=None,
            token_uri="http://localhost:9002/.well-known/agent-card.json",
        )
        db_session.add_all([agent_a, agent_b])
        db_session.commit()

        pub = await registry_client.publish_order(
            agent_a.agent_id,
            OrderRequest(
                offer={"gpu_model": "A100", "region": "us-west"},
                demand={"token": "USDC", "amount": 100.0},
                duration_hours=1.0,
            ),
            private_key=MAKER_PRIVATE_KEY,
        )
        order_id = pub["order_id"]

        all_orders = await registry_client.list_orders(status=None)
        assert any(str(o.id) == order_id for o in all_orders.orders)

        order = await registry_client.get_order(order_id)
        assert isinstance(order, OrderSummary)
        assert order.status == "open"

        # PUT is not yet a client method; use _request directly
        put = await registry_client._request(
            "PUT", f"/orders/{order_id}",
            json={"status": "accepted", "order_taker": agent_b.token_uri},
        )
        assert put["status"] == "accepted"

        updated = await registry_client.get_order(order_id)
        assert updated.status == "accepted"

        await registry_client.delete_order(order_id, private_key=MAKER_PRIVATE_KEY)
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_order(order_id)
        assert exc_info.value.status_code == 404
