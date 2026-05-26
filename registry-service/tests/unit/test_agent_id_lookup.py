"""Unit tests for agent ID lookup functionality."""

import pytest
from src.api.utils import find_agent_by_id
from src.db.models import Agent


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


def test_find_agent_by_bare_numeric_id(db_session, sample_agent, monkeypatch):
    """A bare numeric ID resolves against the registry's configured
    (chain_id, identity_registry_address). One registry indexes one
    (chain, registry) tuple in normal deployments, so onchain_agent_id
    alone is unambiguous.
    """
    from src.config import settings

    monkeypatch.setattr(settings, "chain_id", sample_agent.chain_id)
    monkeypatch.setattr(
        settings,
        "identity_registry_address",
        sample_agent.identity_registry,
    )

    agent = find_agent_by_id(db_session, str(sample_agent.onchain_agent_id))
    assert agent is not None
    assert agent.agent_id == sample_agent.agent_id


def test_find_agent_bare_numeric_unconfigured_chain(db_session, sample_agent, monkeypatch):
    """When the registry's configured chain doesn't match any indexed
    agent's chain, a bare numeric lookup returns None — no silent
    cross-chain match.
    """
    from src.config import settings

    monkeypatch.setattr(settings, "chain_id", sample_agent.chain_id + 1)
    monkeypatch.setattr(
        settings,
        "identity_registry_address",
        sample_agent.identity_registry,
    )

    agent = find_agent_by_id(db_session, str(sample_agent.onchain_agent_id))
    assert agent is None

