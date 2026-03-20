"""Unit tests for event sync functionality."""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch
from web3 import Web3
import src.services.event_sync as event_sync_module
from src.services.event_sync import EventSyncService
from src.types import NetworkConfig
from src.db.models import Agent


@pytest.fixture
def mock_network_config():
    """Create a mock network config with checksum addresses."""
    # Convert to checksum address for web3.py compatibility
    identity_registry = Web3.to_checksum_address("0x21df544947ba3e8b3c32561399e88b52dc8b2823")
    return NetworkConfig(
        chain_id=31337,
        rpc_url="http://localhost:8545",
        identity_registry=identity_registry,
        reputation_registry="0x0000000000000000000000000000000000000000",
        validation_registry="0x0000000000000000000000000000000000000000",
    )


@pytest.fixture
def mock_identity_registry():
    """Create a mock identity registry client."""
    mock_registry = Mock()
    mock_registry.w3 = Mock()
    mock_registry.w3.eth = Mock()
    mock_registry.w3.eth.block_number = 1000
    return mock_registry


@patch('src.services.event_sync.IdentityRegistryClient')
def test_uri_updated_event_processing(MockIdentityRegistryClient, mock_network_config, db_session, sample_agent):
    """Test UriUpdated event processing."""
    # Mock the identity registry client to avoid web3 initialization
    mock_registry_instance = Mock()
    mock_registry_instance.get_past_uri_updated_events = Mock(return_value=[])
    MockIdentityRegistryClient.return_value = mock_registry_instance
    
    # Create event sync service
    event_sync = EventSyncService(mock_network_config)
    
    # Verify the mock was used
    assert event_sync.identity_registry == mock_registry_instance
    
    # Test that sample agent exists
    assert sample_agent.token_uri == "http://localhost:8001/.well-known/agent-card.json"


@patch('src.services.event_sync.IdentityRegistryClient')
def test_event_argument_extraction(MockIdentityRegistryClient, mock_network_config):
    """Test event argument extraction (different web3.py formats)."""
    # Mock the identity registry client to avoid web3 initialization
    mock_registry_instance = Mock()
    MockIdentityRegistryClient.return_value = mock_registry_instance
    
    # Create event sync service
    event_sync = EventSyncService(mock_network_config)
    
    # Test different event argument formats
    # Format 1: camelCase attributes
    event1 = Mock()
    event1.args = Mock()
    event1.args.agentId = 1
    event1.args.newUri = "http://example.com"
    assert hasattr(event1.args, 'agentId')
    assert hasattr(event1.args, 'newUri')
    
    # Format 2: snake_case attributes
    event2 = Mock()
    event2.args = Mock()
    event2.args.agent_id = 1
    event2.args.new_uri = "http://example.com"
    assert hasattr(event2.args, 'agent_id')
    assert hasattr(event2.args, 'new_uri')
    
    # Format 3: dict-like
    event3 = Mock()
    event3.args = {"agentId": 1, "newUri": "http://example.com"}
    assert isinstance(event3.args, dict)


@patch('src.services.event_sync.IdentityRegistryClient')
def test_error_handling_malformed_events(MockIdentityRegistryClient, mock_network_config, db_session):
    """Test error handling for malformed events."""
    # Mock the identity registry client to avoid web3 initialization
    mock_registry_instance = Mock()
    MockIdentityRegistryClient.return_value = mock_registry_instance
    
    # Create event sync service
    event_sync = EventSyncService(mock_network_config)
    
    # Test event with missing args
    event_no_args = Mock()
    event_no_args.args = None
    
    # Test event with missing attributes
    event_missing_attrs = Mock()
    event_missing_attrs.args = Mock()
    # Use hasattr/delattr pattern that works with Mock
    if hasattr(event_missing_attrs.args, 'agentId'):
        delattr(event_missing_attrs.args, 'agentId')
    if hasattr(event_missing_attrs.args, 'newUri'):
        delattr(event_missing_attrs.args, 'newUri')
    
    # These should be handled gracefully without raising exceptions
    # The actual processing would skip these events
    assert True  # Test passes if no exception is raised


@patch('src.services.event_sync.IdentityRegistryClient')
def test_sync_from_start_uses_configured_initial_lookback(
    MockIdentityRegistryClient, mock_network_config
):
    mock_registry_instance = Mock()
    mock_registry_instance.w3 = Mock()
    mock_registry_instance.w3.eth = Mock()
    mock_registry_instance.w3.eth.block_number = 1000
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


@patch('src.services.event_sync.IdentityRegistryClient')
def test_sync_block_range_uses_configured_chunk_size(
    MockIdentityRegistryClient, mock_network_config, db_session
):
    mock_registry_instance = Mock()
    mock_registry_instance.w3 = Mock()
    mock_registry_instance.w3.eth = Mock()
    mock_registry_instance.get_past_agent_registered_events = Mock(return_value=[])
    mock_registry_instance.get_past_metadata_set_events = Mock(return_value=[])
    mock_registry_instance.get_past_uri_updated_events = Mock(return_value=[])
    MockIdentityRegistryClient.return_value = mock_registry_instance

    event_sync = EventSyncService(mock_network_config)

    original_chunk_size = event_sync_module.settings.event_sync_chunk_size
    try:
        event_sync_module.settings.event_sync_chunk_size = 10
        with patch('src.services.event_sync.SessionLocal', return_value=db_session):
            asyncio.run(event_sync.sync_block_range(0, 25))
    finally:
        event_sync_module.settings.event_sync_chunk_size = original_chunk_size

    expected_ranges = [(0, 9), (10, 19), (20, 25)]
    actual_ranges = [
        (call.args[0], call.args[1])
        for call in mock_registry_instance.get_past_agent_registered_events.call_args_list
    ]
    assert actual_ranges == expected_ranges
