"""Unit tests for event sync functionality."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from web3 import Web3

import src.services.event_sync as event_sync_module
from src.db.models import Agent
from src.services.event_sync import EventSyncService
from src.types import NetworkConfig


REGISTRY_ADDRESS = "0x21df544947ba3e8b3c32561399e88b52dc8b2823"


@pytest.fixture
def mock_network_config() -> NetworkConfig:
    """Create a mock network config with checksum addresses."""
    return NetworkConfig(
        chain_id=31337,
        rpc_url="http://localhost:8545",
        identity_registry=Web3.to_checksum_address(REGISTRY_ADDRESS),
        reputation_registry="0x0000000000000000000000000000000000000000",
        validation_registry="0x0000000000000000000000000000000000000000",
    )


def _build_registry_mock() -> Mock:
    mock_registry = Mock()
    mock_registry.w3 = Mock()
    mock_registry.w3.eth = Mock()
    mock_registry.w3.eth.block_number = 1000
    mock_registry.get_past_agent_registered_events = Mock(return_value=[])
    mock_registry.get_past_metadata_set_events = Mock(return_value=[])
    mock_registry.get_past_uri_updated_events = Mock(return_value=[])
    return mock_registry


def _apply_sync_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(event_sync_module.settings, "chain_id", 31337)
    monkeypatch.setattr(event_sync_module.settings, "identity_registry_address", REGISTRY_ADDRESS)


@patch("src.services.event_sync.IdentityRegistryClient")
def test_extract_event_arg_handles_supported_web3_event_shapes(
    MockIdentityRegistryClient: Mock,
    mock_network_config: NetworkConfig,
) -> None:
    MockIdentityRegistryClient.return_value = _build_registry_mock()
    event_sync = EventSyncService(mock_network_config)

    assert (
        event_sync._extract_event_arg(SimpleNamespace(agentId=1), "agentId", "agent_id")
        == 1
    )
    assert (
        event_sync._extract_event_arg(SimpleNamespace(agent_id=2), "agentId", "agent_id")
        == 2
    )
    assert event_sync._extract_event_arg({"agentId": 3}, "agentId", "agent_id") == 3
    assert event_sync._extract_event_arg(("tuple-value",), "agentId") == "tuple-value"
    assert event_sync._extract_event_arg(None, "agentId") is None
    assert event_sync._extract_event_arg(SimpleNamespace(), "agentId") is None


@patch("src.services.event_sync.IdentityRegistryClient")
def test_sync_block_range_skips_malformed_events_without_mutating_db(
    MockIdentityRegistryClient: Mock,
    mock_network_config: NetworkConfig,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _apply_sync_settings(monkeypatch)
    mock_registry = _build_registry_mock()
    mock_registry.get_past_agent_registered_events.return_value = [
        SimpleNamespace(args=None),
        SimpleNamespace(args=SimpleNamespace()),
    ]
    mock_registry.get_past_metadata_set_events.return_value = [
        SimpleNamespace(args=None),
        SimpleNamespace(args={"agentId": 1}),
    ]
    mock_registry.get_past_uri_updated_events.return_value = [
        SimpleNamespace(args=None),
        SimpleNamespace(args=SimpleNamespace(agentId=1)),
    ]
    MockIdentityRegistryClient.return_value = mock_registry

    event_sync = EventSyncService(mock_network_config)
    with patch("src.services.event_sync.SessionLocal", return_value=db_session):
        with caplog.at_level("WARNING"):
            asyncio.run(event_sync.sync_block_range(0, 0))

    assert db_session.query(Agent).count() == 0
    assert "Event missing args" in caplog.text
    assert "Could not extract agentId from event" in caplog.text
    assert "MetadataUpdated event missing args" in caplog.text
    assert "Could not extract agentId/key from MetadataSet event" in caplog.text
    assert "UriUpdated event missing args" in caplog.text
    assert "Could not extract agentId/newUri from UriUpdated event" in caplog.text


@patch("src.services.event_sync.IdentityRegistryClient")
def test_sync_block_range_updates_token_uri_from_uri_updated_event(
    MockIdentityRegistryClient: Mock,
    mock_network_config: NetworkConfig,
    db_session,
    sample_agent: Agent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_sync_settings(monkeypatch)
    sample_agent_id = sample_agent.id
    mock_registry = _build_registry_mock()
    mock_registry.get_past_uri_updated_events.return_value = [
        SimpleNamespace(
            args=SimpleNamespace(agent_id=sample_agent.onchain_agent_id, new_uri="http://example.com/updated.json"),
            block_number=15,
        )
    ]
    MockIdentityRegistryClient.return_value = mock_registry

    event_sync = EventSyncService(mock_network_config)
    with patch("src.services.event_sync.SessionLocal", return_value=db_session):
        asyncio.run(event_sync.sync_block_range(10, 15))

    db_session.expire_all()
    refreshed = db_session.query(Agent).filter(Agent.id == sample_agent_id).one()
    assert refreshed.token_uri == "http://example.com/updated.json"


@patch("src.services.event_sync.IdentityRegistryClient")
def test_sync_from_start_uses_configured_initial_lookback(
    MockIdentityRegistryClient: Mock,
    mock_network_config: NetworkConfig,
) -> None:
    mock_registry_instance = _build_registry_mock()
    MockIdentityRegistryClient.return_value = mock_registry_instance

    event_sync = EventSyncService(mock_network_config)
    event_sync.sync_block_range = AsyncMock()

    original_lookback = event_sync_module.settings.event_sync_initial_lookback_blocks
    try:
        event_sync_module.settings.event_sync_initial_lookback_blocks = 25
        asyncio.run(event_sync.sync_from_start())
    finally:
        event_sync_module.settings.event_sync_initial_lookback_blocks = original_lookback

    event_sync.sync_block_range.assert_awaited_once_with(975, 1000)


@patch("src.services.event_sync.IdentityRegistryClient")
def test_sync_block_range_uses_configured_chunk_size(
    MockIdentityRegistryClient: Mock,
    mock_network_config: NetworkConfig,
    db_session,
) -> None:
    mock_registry_instance = _build_registry_mock()
    MockIdentityRegistryClient.return_value = mock_registry_instance

    event_sync = EventSyncService(mock_network_config)

    original_chunk_size = event_sync_module.settings.event_sync_chunk_size
    try:
        event_sync_module.settings.event_sync_chunk_size = 10
        with patch("src.services.event_sync.SessionLocal", return_value=db_session):
            asyncio.run(event_sync.sync_block_range(0, 25))
    finally:
        event_sync_module.settings.event_sync_chunk_size = original_chunk_size

    expected_ranges = [(0, 9), (10, 19), (20, 25)]
    actual_ranges = [
        (call.args[0], call.args[1])
        for call in mock_registry_instance.get_past_agent_registered_events.call_args_list
    ]
    assert actual_ranges == expected_ranges
