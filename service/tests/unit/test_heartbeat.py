"""Unit tests for service.clients.erc8004.heartbeat."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_send_heartbeat_success():
    from service.clients.erc8004.heartbeat import send_heartbeat

    mock_response = AsyncMock()
    mock_response.status = 200

    with patch("aiohttp.ClientSession") as mock_session_cls:
        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=session_instance)
        session_instance.__aexit__ = AsyncMock(return_value=False)
        post_cm = MagicMock()
        post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        post_cm.__aexit__ = AsyncMock(return_value=False)
        session_instance.post = MagicMock(return_value=post_cm)
        mock_session_cls.return_value = session_instance

        result = await send_heartbeat("agent1", "http://indexer:8080")
    assert result is True


@pytest.mark.asyncio
async def test_send_heartbeat_404():
    from service.clients.erc8004.heartbeat import send_heartbeat

    mock_response = AsyncMock()
    mock_response.status = 404

    with patch("aiohttp.ClientSession") as mock_session_cls:
        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=session_instance)
        session_instance.__aexit__ = AsyncMock(return_value=False)
        post_cm = MagicMock()
        post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        post_cm.__aexit__ = AsyncMock(return_value=False)
        session_instance.post = MagicMock(return_value=post_cm)
        mock_session_cls.return_value = session_instance

        result = await send_heartbeat("agent1", "http://indexer:8080")
    assert result is False


@pytest.mark.asyncio
async def test_send_heartbeat_sends_bearer_header():
    """When a bearer_token is provided, Authorization header is set."""
    from service.clients.erc8004.heartbeat import send_heartbeat

    mock_response = AsyncMock()
    mock_response.status = 200
    captured: dict = {}

    with patch("aiohttp.ClientSession") as mock_session_cls:
        session_instance = MagicMock()
        session_instance.__aenter__ = AsyncMock(return_value=session_instance)
        session_instance.__aexit__ = AsyncMock(return_value=False)
        post_cm = MagicMock()
        post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        post_cm.__aexit__ = AsyncMock(return_value=False)

        def _post(*args, **kwargs):
            captured["headers"] = kwargs.get("headers")
            return post_cm

        session_instance.post = MagicMock(side_effect=_post)
        mock_session_cls.return_value = session_instance

        result = await send_heartbeat(
            "agent1", "http://indexer:8080", bearer_token="secret-token"
        )
    assert result is True
    assert captured["headers"] == {"Authorization": "Bearer secret-token"}


@pytest.mark.asyncio
async def test_start_agent_heartbeat_missing_config():
    from service.clients.erc8004.heartbeat import start_agent_heartbeat
    result = await start_agent_heartbeat({})
    assert result is None


@pytest.mark.asyncio
async def test_start_agent_heartbeat_missing_agent_id():
    from service.clients.erc8004.heartbeat import start_agent_heartbeat
    result = await start_agent_heartbeat({
        "indexer_url": "http://indexer:8080",
        "identity_registry_address": "0x1234",
        "agent_wallet_address": "0xABCD",
        # no onchain_agent_id
    })
    assert result is None
