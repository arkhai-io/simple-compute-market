"""Unit tests for agent ID lookup."""

from src.api.utils import find_agent_by_id


def test_find_agent_by_canonical_id(db_session, sample_agent):
    """Legacy eip155:... canonical ID still resolves via the back-compat
    agent_id column (rows backfilled by migration 012)."""
    canonical_id = sample_agent.agent_id
    agent = find_agent_by_id(db_session, canonical_id)
    assert agent is not None
    assert agent.agent_id == canonical_id


def test_find_agent_by_eip191_address(db_session, sample_agent):
    """A 0x... wallet address resolves via the scheme-tagged lookup."""
    sample_agent.scheme = "eip191"
    sample_agent.identifier = sample_agent.owner.lower()
    db_session.commit()

    agent = find_agent_by_id(db_session, sample_agent.owner.lower())
    assert agent is not None
    assert agent.identifier == sample_agent.owner.lower()


def test_find_agent_not_found(db_session):
    assert find_agent_by_id(db_session, "nonexistent") is None


def test_find_agent_by_invalid_canonical_id(db_session):
    assert find_agent_by_id(db_session, "invalid-format") is None
