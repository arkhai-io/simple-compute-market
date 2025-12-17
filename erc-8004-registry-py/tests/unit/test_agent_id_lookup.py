"""Unit tests for agent ID lookup functionality."""

import pytest
from src.api.utils import find_agent_by_id
from src.db.models import Agent


def test_find_agent_by_integer_pk(db_session, sample_agent):
    """Test finding agent by integer primary key."""
    agent = find_agent_by_id(db_session, "1")
    assert agent is not None
    assert agent.id == 1
    assert agent.agent_id == sample_agent.agent_id


def test_find_agent_by_canonical_id(db_session, sample_agent):
    """Test finding agent by canonical ID."""
    canonical_id = sample_agent.agent_id
    agent = find_agent_by_id(db_session, canonical_id)
    assert agent is not None
    assert agent.agent_id == canonical_id


def test_find_agent_by_parsed_components(db_session, sample_agent):
    """Test finding agent by parsing canonical ID."""
    # Test with different case in registry address
    canonical_id = sample_agent.agent_id
    canonical_id_upper = canonical_id.replace(
        "0x21df544947ba3e8b3c32561399e88b52dc8b2823",
        "0x21DF544947BA3E8B3C32561399E88B52DC8B2823"
    )
    agent = find_agent_by_id(db_session, canonical_id_upper)
    assert agent is not None
    assert agent.agent_id == sample_agent.agent_id


def test_find_agent_not_found(db_session):
    """Test agent not found returns None."""
    agent = find_agent_by_id(db_session, "nonexistent")
    assert agent is None


def test_find_agent_by_invalid_canonical_id(db_session):
    """Test finding agent with invalid canonical ID format."""
    agent = find_agent_by_id(db_session, "invalid-format")
    assert agent is None

