"""Unit tests for service.clients.indexer."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp


PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
AGENT_ID = "eip155:31337:0xregistry:1"


@pytest.fixture
def client():
    from service.clients.indexer import RegistryClient
    return RegistryClient(base_url="http://test-indexer:8080", timeout=5)


@pytest.fixture
def auth_client():
    """RegistryClient configured with a private key and agent_id for signing."""
    from service.clients.indexer import RegistryClient
    return RegistryClient(
        base_url="http://test-indexer:8080",
        timeout=5,
        private_key=PRIVATE_KEY,
        agent_id=AGENT_ID,
    )


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


@pytest.mark.asyncio
async def test_publish_order_attaches_signature(auth_client):
    """When private_key is set, publish_order adds signature+timestamp to the payload."""
    pytest.importorskip("eth_account")
    captured = {}
    mock_response = AsyncMock()
    mock_response.status = 201
    mock_response.json = AsyncMock(return_value={"order_id": "ord1"})
    mock_session = AsyncMock()

    def capture_post(url, json=None, **kwargs):
        captured["payload"] = json
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_response)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_session.post = MagicMock(side_effect=capture_post)
    with patch.object(auth_client, "_get_session", return_value=mock_session):
        await auth_client.publish_order(AGENT_ID, {"order_id": "ord1"})

    assert "signature" in captured["payload"]
    assert "timestamp" in captured["payload"]


@pytest.mark.asyncio
async def test_publish_order_no_private_key_no_signature(client):
    """Without a private key, no auth fields are added to the payload."""
    captured = {}
    mock_response = AsyncMock()
    mock_response.status = 201
    mock_response.json = AsyncMock(return_value={"order_id": "ord1"})
    mock_session = AsyncMock()

    def capture_post(url, json=None, **kwargs):
        captured["payload"] = json
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_response)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_session.post = MagicMock(side_effect=capture_post)
    with patch.object(client, "_get_session", return_value=mock_session):
        await client.publish_order("agent1", {"order_id": "ord1"})

    assert "signature" not in captured["payload"]
    assert "timestamp" not in captured["payload"]


@pytest.mark.asyncio
async def test_update_order_attaches_signature_and_signer_id(auth_client):
    """update_order includes signature, timestamp, and signer_agent_id when credentialed."""
    pytest.importorskip("eth_account")
    captured = {}
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"order_id": "ord1", "status": "closed"})
    mock_session = AsyncMock()

    def capture_put(url, json=None, **kwargs):
        captured["payload"] = json
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_response)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_session.put = MagicMock(side_effect=capture_put)
    with patch.object(auth_client, "_get_session", return_value=mock_session):
        await auth_client.update_order("ord1", {"status": "closed"})

    assert "signature" in captured["payload"]
    assert "timestamp" in captured["payload"]
    assert captured["payload"]["signer_agent_id"] == AGENT_ID


@pytest.mark.asyncio
async def test_delete_order_attaches_signature_as_query_params(auth_client):
    """delete_order passes signature and timestamp as query params when credentialed."""
    pytest.importorskip("eth_account")
    captured = {}
    mock_response = AsyncMock()
    mock_response.status = 204
    mock_session = AsyncMock()

    def capture_delete(url, params=None, **kwargs):
        captured["params"] = params
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_response)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_session.delete = MagicMock(side_effect=capture_delete)
    with patch.object(auth_client, "_get_session", return_value=mock_session):
        await auth_client.delete_order("ord1")

    assert "signature" in captured["params"]
    assert "timestamp" in captured["params"]


@pytest.mark.asyncio
async def test_delete_order_no_private_key_empty_params(client):
    """Without a private key, delete_order sends no query params."""
    captured = {}
    mock_response = AsyncMock()
    mock_response.status = 204
    mock_session = AsyncMock()

    def capture_delete(url, params=None, **kwargs):
        captured["params"] = params
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=mock_response)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    mock_session.delete = MagicMock(side_effect=capture_delete)
    with patch.object(client, "_get_session", return_value=mock_session):
        await client.delete_order("ord1")

    assert captured["params"] == {}


def test_get_registry_client_singleton():
    import service.clients.indexer as idx
    idx._registry_client = None  # reset singleton
    idx._registry_client_config = None
    idx.configure_registry_client(idx.RegistryClientConfig(
        base_url="http://test-indexer:8080",
        timeout=15,
    ))
    c1 = idx.get_registry_client()
    c2 = idx.get_registry_client()
    assert c1 is c2
    idx._registry_client = None  # cleanup
    idx._registry_client_config = None


def test_get_registry_client_unconfigured_raises():
    import service.clients.indexer as idx
    idx._registry_client = None
    idx._registry_client_config = None
    with pytest.raises(RuntimeError, match="not configured"):
        idx.get_registry_client()
