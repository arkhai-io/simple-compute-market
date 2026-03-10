"""Unit tests for service.clients.indexer."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp


@pytest.fixture
def client():
    from service.clients.indexer import RegistryClient
    return RegistryClient(base_url="http://test-indexer:8080", timeout=5)


@pytest.mark.asyncio
async def test_discover_agents_success(client):
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"items": [{"id": "agent1"}]})
    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))
    with patch.object(client, "_get_session", return_value=mock_session):
        result = await client.discover_agents()
    assert result == [{"id": "agent1"}]


@pytest.mark.asyncio
async def test_discover_agents_failure(client):
    mock_response = AsyncMock()
    mock_response.status = 500
    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))
    with patch.object(client, "_get_session", return_value=mock_session):
        result = await client.discover_agents()
    assert result == []


@pytest.mark.asyncio
async def test_publish_order_success(client):
    mock_response = AsyncMock()
    mock_response.status = 201
    mock_response.json = AsyncMock(return_value={"order_id": "ord1"})
    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))
    with patch.object(client, "_get_session", return_value=mock_session):
        result = await client.publish_order("agent1", {"order_id": "ord1"})
    assert result == {"order_id": "ord1"}


@pytest.mark.asyncio
async def test_update_order_success(client):
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"order_id": "ord1", "status": "accepted"})
    mock_session = AsyncMock()
    mock_session.put = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))
    with patch.object(client, "_get_session", return_value=mock_session):
        result = await client.update_order("ord1", {"status": "accepted"})
    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_delete_order_success(client):
    mock_response = AsyncMock()
    mock_response.status = 204
    mock_session = AsyncMock()
    mock_session.delete = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock(return_value=False)))
    with patch.object(client, "_get_session", return_value=mock_session):
        result = await client.delete_order("ord1")
    assert result is True


def test_get_registry_client_singleton(monkeypatch):
    monkeypatch.setenv("REGISTRY_ORDER_TIMEOUT", "15")
    import service.clients.indexer as idx
    idx._registry_client = None  # reset singleton
    c1 = idx.get_registry_client()
    c2 = idx.get_registry_client()
    assert c1 is c2
    idx._registry_client = None  # cleanup
