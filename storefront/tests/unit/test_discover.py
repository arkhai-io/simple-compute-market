"""Unit tests for `discover()` — the pure registry-query step.

Verifies the filter stack: bidirectional match → drop own orders →
drop active negotiations → cap at max_discovery_agents → shape the
return. No thread writes, no dispatch; the function is a pure read.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from registry_client.models import ListingListResponse, ListingSummary

from market_storefront.utils.action_executor import discover

# Canonical complementary resource pair used across fixtures.
# Buyer: demands compute (GPU), offers token payment.
# Seller: offers compute (GPU), demands token payment.
_BUYER_OFFER = {"token": "USDC"}
_BUYER_DEMAND = {"gpu_model": "H200"}
_SELLER_OFFER = {"gpu_model": "H200"}
_SELLER_DEMAND = {"token": "USDC"}


def _buyer_order(order_id: str, order_maker: str) -> ListingSummary:
    """Construct a buyer-role ListingSummary (demands compute, offers token)."""
    return ListingSummary(
        id=order_id,
        maker_agent_id=order_maker,
        offer=_BUYER_OFFER,
        demand=_BUYER_DEMAND,
    )


def _seller_order(order_id: str, order_maker: str) -> ListingSummary:
    """Construct a seller-role ListingSummary (offers compute, demands token)."""
    return ListingSummary(
        id=order_id,
        maker_agent_id=order_maker,
        offer=_SELLER_OFFER,
        demand=_SELLER_DEMAND,
    )


def _mock_registry(*, our_order: ListingSummary, candidates: list[ListingSummary]):
    """Build a registry_client mock that returns the given fixtures.

    Wraps the client in an async context manager to match the
    ``async with _make_registry_client() as registry_client:`` pattern.
    """
    client = MagicMock()
    client.get_listing = AsyncMock(return_value=our_order)
    client.list_listings = AsyncMock(
        return_value=ListingListResponse(listings=candidates)
    )
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _mock_thread_txn(active_order_ids: set[str] | None = None):
    """Build a NegotiationThreadTransaction context-manager mock."""
    txn = MagicMock()
    txn.filter_active = AsyncMock(return_value=active_order_ids or set())
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=None)
    return txn


@pytest.mark.asyncio
async def test_discover_happy_path_returns_structured_matches():
    our_order = _buyer_order("buyer-ord-1", "http://buyer:8000")
    peer_order = _seller_order("seller-ord-1", "http://seller:8001")

    with (
        patch("market_storefront.utils.action_executor._make_registry_client",
              return_value=_mock_registry(our_order=our_order, candidates=[peer_order])),
        patch("market_storefront.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("market_storefront.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert len(matches) == 1
    m = matches[0]
    assert m["their_order_id"] == "seller-ord-1"
    assert m["their_agent_url"] == "http://seller:8001"
    assert m["their_order"] is peer_order


@pytest.mark.asyncio
async def test_discover_filters_out_our_own_orders():
    our_order = _buyer_order("buyer-ord-1", "http://buyer:8000")
    candidates = [
        # Same order_id → drop
        _seller_order("buyer-ord-1", "http://buyer:8000"),
        # Same maker (different order_id) → drop
        _seller_order("another-ours", "http://buyer:8000"),
        # Legit peer
        _seller_order("seller-ord-1", "http://seller:8001"),
    ]

    with (
        patch("market_storefront.utils.action_executor._make_registry_client",
              return_value=_mock_registry(our_order=our_order, candidates=candidates)),
        patch("market_storefront.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("market_storefront.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert len(matches) == 1
    assert matches[0]["their_order_id"] == "seller-ord-1"


@pytest.mark.asyncio
async def test_discover_drops_active_negotiations_by_default():
    our_order = _buyer_order("buyer-ord-1", "http://buyer:8000")
    candidates = [
        _seller_order("already-active", "http://peer1:8000"),
        _seller_order("fresh", "http://peer2:8000"),
    ]

    with (
        patch("market_storefront.utils.action_executor._make_registry_client",
              return_value=_mock_registry(our_order=our_order, candidates=candidates)),
        patch("market_storefront.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn(active_order_ids={"already-active"})),
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("market_storefront.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert [m["their_order_id"] for m in matches] == ["fresh"]


@pytest.mark.asyncio
async def test_discover_include_active_skips_the_filter():
    our_order = _buyer_order("buyer-ord-1", "http://buyer:8000")
    candidates = [
        _seller_order("already-active", "http://peer1:8000"),
        _seller_order("fresh", "http://peer2:8000"),
    ]

    with (
        patch("market_storefront.utils.action_executor._make_registry_client",
              return_value=_mock_registry(our_order=our_order, candidates=candidates)),
        patch("market_storefront.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn(active_order_ids={"already-active"})),
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("market_storefront.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1", include_active_negotiations=True)

    assert sorted(m["their_order_id"] for m in matches) == ["already-active", "fresh"]


@pytest.mark.asyncio
async def test_discover_caps_at_max_discovery_agents():
    our_order = _buyer_order("buyer-ord-1", "http://buyer:8000")
    candidates = [_seller_order(f"peer-{i}", f"http://peer{i}:8000") for i in range(20)]

    with (
        patch("market_storefront.utils.action_executor._make_registry_client",
              return_value=_mock_registry(our_order=our_order, candidates=candidates)),
        patch("market_storefront.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=3)),
        patch("market_storefront.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert len(matches) == 3


@pytest.mark.asyncio
async def test_discover_refuses_when_registry_discovery_disabled():
    with (
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=False)),
    ):
        with pytest.raises(RuntimeError, match="Registry discovery is disabled"):
            await discover(order_id="buyer-ord-1")


@pytest.mark.asyncio
async def test_discover_raises_when_order_not_in_registry():
    from registry_client import RegistryClientError

    client = MagicMock()
    client.get_listing = AsyncMock(
        side_effect=RegistryClientError("GET", "/orders/phantom", 404, "not found")
    )
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("market_storefront.utils.action_executor._make_registry_client", return_value=cm),
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
    ):
        with pytest.raises(ValueError, match="not found in registry"):
            await discover(order_id="phantom")


@pytest.mark.asyncio
async def test_discover_skips_matches_missing_fields():
    """Registry entries with no maker_agent_id or empty id are silently dropped.

    The guard in discover() is ``if not their_order_id or not their_agent_url``.
    - Empty string id (``id=""``) → str("") is falsy → dropped.
    - None maker_agent_id → falsy → dropped.
    Note: ``id=None`` produces ``str(None) == "None"`` which is truthy and is NOT
    dropped by the current guard — that is a known pre-existing gap, not tested here.
    """
    our_order = _buyer_order("buyer-ord-1", "http://buyer:8000")
    candidates = [
        # Empty id string → str("") is falsy → dropped.
        ListingSummary(id="", maker_agent_id="http://peer1:8000",
                     offer=_SELLER_OFFER, demand=_SELLER_DEMAND),
        # Missing maker_agent_id → None is falsy → dropped.
        ListingSummary(id="no-maker", maker_agent_id=None,
                     offer=_SELLER_OFFER, demand=_SELLER_DEMAND),
        _seller_order("good", "http://peer2:8000"),
    ]

    with (
        patch("market_storefront.utils.action_executor._make_registry_client",
              return_value=_mock_registry(our_order=our_order, candidates=candidates)),
        patch("market_storefront.utils.action_executor.NegotiationThreadTransaction",
              return_value=_mock_thread_txn()),
        patch("market_storefront.utils.action_executor.CONFIG",
              MagicMock(enable_registry_discovery=True, max_discovery_agents=10)),
        patch("market_storefront.utils.action_executor.BASE_URL_OVERRIDE", "http://buyer:8000"),
    ):
        matches = await discover(order_id="buyer-ord-1")

    assert [m["their_order_id"] for m in matches] == ["good"]