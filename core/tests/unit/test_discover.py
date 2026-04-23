"""Unit tests for `discover()` — the pure registry-query step.

Verifies the filter stack: bidirectional match → drop own orders →
drop active negotiations → cap at max_discovery_agents → shape the
return. No thread writes, no dispatch; the function is a pure read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent.app.utils.action_executor import discover


def _mock_registry(*, our_order: dict, matches_for_query: list[dict]):
    """Build a registry_client mock that returns the given fixtures."""
    client = MagicMock()
    client.get_order = AsyncMock(return_value=our_order)
    client.query_orders = AsyncMock(return_value=matches_for_query)
    # match_orders is synchronous and filters based on resource compat;
    # for these tests we pass-through so we can focus on the higher-level
    # filters discover applies itself.
    client.match_orders = lambda our, candidates, bidirectional=True: candidates
    return client


def _mock_thread_txn(active_order_ids: set[str] | None = None):
    """Build a NegotiationThreadTransaction context-manager mock."""
    txn = MagicMock()
    txn.filter_active = AsyncMock(return_value=active_order_ids or set())
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=None)
    return txn


@pytest.mark.asyncio
async def test_discover_happy_path_returns_structured_matches():
    our_order = {"order_id": "buyer-ord-1", "order_maker": "http://buyer:8000"}
    peer_order = {
        "order_id": "seller-ord-1",
        "order_maker": "http://seller:8001",
        "offer_resource": {"gpu_model": "H200"},
    }
    client = _mock_registry(our_order=our_order, matches_for_query=[peer_order])

    with (
        patch("core.agent.app.utils.action_executor.get_registry_client", return_value=client),
        patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert len(matches) == 1
    m = matches[0]
    assert m["their_order_id"] == "seller-ord-1"
    assert m["their_agent_url"] == "http://seller:8001"
    assert m["their_order"] == peer_order


@pytest.mark.asyncio
async def test_discover_filters_out_our_own_orders():
    our_order = {"order_id": "buyer-ord-1", "order_maker": "http://buyer:8000"}
    candidates = [
        # Same order_id → drop
        {"order_id": "buyer-ord-1", "order_maker": "http://buyer:8000"},
        # Same maker (different order_id) → drop
        {"order_id": "another-ours", "order_maker": "http://buyer:8000"},
        # Legit peer
        {"order_id": "seller-ord-1", "order_maker": "http://seller:8001"},
    ]
    client = _mock_registry(our_order=our_order, matches_for_query=candidates)

    with (
        patch("core.agent.app.utils.action_executor.get_registry_client", return_value=client),
        patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert len(matches) == 1
    assert matches[0]["their_order_id"] == "seller-ord-1"


@pytest.mark.asyncio
async def test_discover_drops_active_negotiations_by_default():
    our_order = {"order_id": "buyer-ord-1", "order_maker": "http://buyer:8000"}
    candidates = [
        {"order_id": "already-active", "order_maker": "http://peer1:8000"},
        {"order_id": "fresh", "order_maker": "http://peer2:8000"},
    ]
    client = _mock_registry(our_order=our_order, matches_for_query=candidates)

    with (
        patch("core.agent.app.utils.action_executor.get_registry_client", return_value=client),
        patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn(active_order_ids={"already-active"})),
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert [m["their_order_id"] for m in matches] == ["fresh"]


@pytest.mark.asyncio
async def test_discover_include_active_skips_the_filter():
    our_order = {"order_id": "buyer-ord-1", "order_maker": "http://buyer:8000"}
    candidates = [
        {"order_id": "already-active", "order_maker": "http://peer1:8000"},
        {"order_id": "fresh", "order_maker": "http://peer2:8000"},
    ]
    client = _mock_registry(our_order=our_order, matches_for_query=candidates)

    with (
        patch("core.agent.app.utils.action_executor.get_registry_client", return_value=client),
        patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn(active_order_ids={"already-active"})),
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1", include_active_negotiations=True)

    assert sorted(m["their_order_id"] for m in matches) == ["already-active", "fresh"]


@pytest.mark.asyncio
async def test_discover_caps_at_max_discovery_agents():
    our_order = {"order_id": "buyer-ord-1", "order_maker": "http://buyer:8000"}
    candidates = [
        {"order_id": f"peer-{i}", "order_maker": f"http://peer{i}:8000"}
        for i in range(20)
    ]
    client = _mock_registry(our_order=our_order, matches_for_query=candidates)

    with (
        patch("core.agent.app.utils.action_executor.get_registry_client", return_value=client),
        patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=3)),
        patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert len(matches) == 3


@pytest.mark.asyncio
async def test_discover_refuses_when_registry_discovery_disabled():
    with (
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=False)),
    ):
        with pytest.raises(RuntimeError, match="Registry discovery is disabled"):
            await discover(order_id="buyer-ord-1")


@pytest.mark.asyncio
async def test_discover_raises_when_order_not_in_registry():
    client = MagicMock()
    client.get_order = AsyncMock(return_value=None)

    with (
        patch("core.agent.app.utils.action_executor.get_registry_client", return_value=client),
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
    ):
        with pytest.raises(ValueError, match="not found in registry"):
            await discover(order_id="phantom")


@pytest.mark.asyncio
async def test_discover_skips_matches_missing_fields():
    """Registry entries with no order_id or no order_maker are silently dropped."""
    our_order = {"order_id": "buyer-ord-1", "order_maker": "http://buyer:8000"}
    candidates = [
        {"order_maker": "http://peer1:8000"},  # missing order_id
        {"order_id": "no-maker"},              # missing maker
        {"order_id": "good", "order_maker": "http://peer2:8000"},
    ]
    client = _mock_registry(our_order=our_order, matches_for_query=candidates)

    with (
        patch("core.agent.app.utils.action_executor.get_registry_client", return_value=client),
        patch("core.agent.app.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("core.agent.app.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("core.agent.app.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert [m["their_order_id"] for m in matches] == ["good"]
