"""Integration tests for the agents API."""

from __future__ import annotations

import pytest

from registry_client import RegistryClientError
from registry_client.models import AgentListResponse, AgentSummary, ListingRequest
from tests.integration.conftest import (
    IDENTITY_REGISTRY,
    MAKER_PRIVATE_KEY,
    TAKER_PRIVATE_KEY,
)


class TestListAgents:
    async def test_empty_registry_returns_empty_list(self, registry_client):
        result = await registry_client.list_agents()
        assert isinstance(result, AgentListResponse)
        assert result.agents == []

    async def test_registered_agent_appears(self, registry_client, maker_agent):
        result = await registry_client.list_agents()
        assert maker_agent.agent_id in [a.agent_id for a in result.agents]

    async def test_all_three_agents_returned(
        self, registry_client, maker_agent, taker_agent, agent_no_owner
    ):
        result = await registry_client.list_agents()
        assert len(result.agents) == 3

    async def test_all_items_are_agent_summary(self, registry_client, maker_agent):
        result = await registry_client.list_agents()
        assert all(isinstance(a, AgentSummary) for a in result.agents)

    async def test_limit_respected(
        self, registry_client, maker_agent, taker_agent, agent_no_owner
    ):
        result = await registry_client.list_agents(limit=1)
        assert len(result.agents) <= 1

    async def test_offset_reduces_count(
        self, registry_client, maker_agent, taker_agent, agent_no_owner
    ):
        all_result = await registry_client.list_agents(limit=10)
        off_result = await registry_client.list_agents(limit=10, offset=1)
        assert len(off_result.agents) == len(all_result.agents) - 1


class TestGetAgent:
    async def test_returns_typed_agent_summary(self, registry_client, maker_agent):
        agent = await registry_client.get_agent(maker_agent.agent_id)
        assert isinstance(agent, AgentSummary)
        assert agent.agent_id == maker_agent.agent_id

    async def test_404_raises_registry_client_error(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.get_agent("eip155:99:0xdeadbeef:999")
        assert exc_info.value.status_code == 404

    async def test_owner_field_populated(self, registry_client, maker_agent):
        agent = await registry_client.get_agent(maker_agent.agent_id)
        assert agent.owner == maker_agent.owner

    async def test_no_owner_agent_owner_is_none(self, registry_client, agent_no_owner):
        agent = await registry_client.get_agent(agent_no_owner.agent_id)
        assert agent.owner is None


class TestSearchAgents:
    async def test_search_returns_matching_agent(self, registry_client, maker_agent):
        result = await registry_client.search_agents("eip155:31337")
        assert maker_agent.agent_id in [a.agent_id for a in result.agents]

    async def test_no_match_returns_empty(self, registry_client, maker_agent):
        result = await registry_client.search_agents("eip155:99999:0xdeadbeef")
        assert result.agents == []

    async def test_returns_agent_list_response(self, registry_client, maker_agent):
        result = await registry_client.search_agents("eip155")
        assert isinstance(result, AgentListResponse)


class TestHeartbeat:
    async def test_valid_heartbeat_accepted(self, registry_client, maker_agent):
        result = await registry_client.send_heartbeat(maker_agent.agent_id, MAKER_PRIVATE_KEY)
        assert result is not None

    async def test_wrong_key_raises_401(self, registry_client, maker_agent):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.send_heartbeat(maker_agent.agent_id, TAKER_PRIVATE_KEY)
        assert exc_info.value.status_code == 401

    async def test_unknown_agent_raises_404(self, registry_client):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.send_heartbeat(
                "eip155:99:0xdeadbeef:999", MAKER_PRIVATE_KEY
            )
        assert exc_info.value.status_code == 404

    async def test_heartbeat_updates_last_heartbeat(
        self, registry_client, maker_agent, db_session
    ):
        from src.db.models import Agent
        await registry_client.send_heartbeat(maker_agent.agent_id, MAKER_PRIVATE_KEY)
        db_session.refresh(maker_agent)
        agent = db_session.query(Agent).filter_by(agent_id=maker_agent.agent_id).first()
        assert agent.last_heartbeat is not None
