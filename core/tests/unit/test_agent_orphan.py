"""Unit tests for TraderAgent._check_orphan — orphaned-negotiation detection after restart.

When the pod restarts, _negotiation_sessions and _negotiation_locks are cleared.
Incoming counter/initial proposals reference ADK context-ids that no longer exist.
_check_orphan detects this and sends exit_negotiation so the counterparty can requeue.
"""

import pytest
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent.app.utils.sqlite_client import SQLiteClient
from core.agent.app.policy.negotiation_thread import NegotiationThreadStore


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def thread_store(temp_db):
    return NegotiationThreadStore(SQLiteClient(db_path=temp_db))


def _make_domain_event(msg_type: str, neg_id: str, their_order_id: str = "order-bob-1"):
    """Build a minimal domain event object for _check_orphan."""
    event = MagicMock()
    event.data = {
        "message_type": msg_type,
        "negotiation_id": neg_id,
        "their_order_id": their_order_id,
    }
    event.message_type = msg_type
    event.negotiation_id = neg_id
    return event


class TestCheckOrphan:
    """Tests for TraderAgent._check_orphan."""

    @pytest.mark.asyncio
    async def test_returns_none_for_non_negotiation_message(self, thread_store):
        """Non-proposal message types are never orphaned."""
        from core.agent.app.agent import TraderAgent
        import core.agent.app.policy.negotiation_thread as nthread_mod

        event = _make_domain_event("make_offer", "neg-1")
        ctx = MagicMock()

        with (
            patch.object(nthread_mod, "_thread_store", thread_store),
            patch("core.agent.app.utils.action_executor._negotiation_sessions", {}),
            patch("core.agent.app.utils.action_executor._negotiation_locks", {}),
        ):
            result = await TraderAgent._check_orphan(MagicMock(), event, ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_first_round_arrival(self, thread_store):
        """counter_proposal with no prior thread history is not an orphan (round-0 arrival)."""
        from core.agent.app.agent import TraderAgent
        import core.agent.app.policy.negotiation_thread as nthread_mod

        neg_id = "neg-orphan-first-round"
        event = _make_domain_event("counter_proposal", neg_id)
        ctx = MagicMock()

        # Thread store has no messages for this negotiation — empty history
        with (
            patch.object(nthread_mod, "_thread_store", thread_store),
            patch("core.agent.app.utils.action_executor._negotiation_sessions", {}),
            patch("core.agent.app.utils.action_executor._negotiation_locks", {}),
        ):
            result = await TraderAgent._check_orphan(MagicMock(), event, ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_active_session_exists(self, thread_store):
        """Not orphaned if _negotiation_sessions has an entry for this negotiation."""
        from core.agent.app.agent import TraderAgent
        import core.agent.app.policy.negotiation_thread as nthread_mod

        neg_id = "neg-has-session"
        event = _make_domain_event("counter_proposal", neg_id)
        ctx = MagicMock()

        # Seed thread with prior messages (would be orphan without active session)
        await thread_store.add_message(
            negotiation_id=neg_id,
            sender="http://alice.local",
            our_price=100, their_price=150, proposed_price=125,
            action_taken="counter_offer", message_type="counter_proposal",
        )

        active_sessions = {neg_id: MagicMock()}  # session exists → not orphaned

        with (
            patch.object(nthread_mod, "_thread_store", thread_store),
            patch("core.agent.app.utils.action_executor._negotiation_sessions", active_sessions),
            patch("core.agent.app.utils.action_executor._negotiation_locks", {}),
        ):
            result = await TraderAgent._check_orphan(MagicMock(), event, ctx)

        assert result is None

    @pytest.mark.asyncio
    async def test_exits_with_prior_history_and_no_session(self, thread_store):
        """Orphan detected: thread has prior messages but no ADK session or lock.

        _check_orphan must:
        - Return a non-None message string
        - Call exit_negotiation with reason='agent_restarted'
        """
        from core.agent.app.agent import TraderAgent
        import core.agent.app.policy.negotiation_thread as nthread_mod

        neg_id = "neg-orphan-restart"
        their_order_id = "order-bob-orphan"
        event = _make_domain_event("counter_proposal", neg_id, their_order_id)
        ctx = MagicMock()

        # Seed thread with 1 prior message (proves this negotiation was already in progress)
        await thread_store.add_message(
            negotiation_id=neg_id,
            sender="http://alice.local",
            our_price=100, their_price=150, proposed_price=125,
            action_taken="counter_offer", message_type="counter_proposal",
        )

        mock_exit = AsyncMock(return_value={"status": "ok"})

        with (
            patch.object(nthread_mod, "_thread_store", thread_store),
            patch("core.agent.app.utils.action_executor._negotiation_sessions", {}),
            patch("core.agent.app.utils.action_executor._negotiation_locks", {}),
            patch("core.agent.app.utils.action_executor.exit_negotiation", mock_exit),
        ):
            result = await TraderAgent._check_orphan(MagicMock(), event, ctx)

        assert result is not None
        assert isinstance(result, str)
        assert "agent_restarted" in result or neg_id in result

        mock_exit.assert_called_once()
        call_kwargs = mock_exit.call_args.kwargs
        assert call_kwargs["parameters"]["negotiation_id"] == neg_id
        assert call_kwargs["parameters"]["reason"] == "agent_restarted"

    @pytest.mark.asyncio
    async def test_initial_proposal_also_detected_as_orphan(self, thread_store):
        """initial_proposal is also subject to orphan detection (not just counter_proposal)."""
        from core.agent.app.agent import TraderAgent
        import core.agent.app.policy.negotiation_thread as nthread_mod

        neg_id = "neg-initial-orphan"
        event = _make_domain_event("initial_proposal", neg_id)
        ctx = MagicMock()

        # Seed thread with prior message
        await thread_store.add_message(
            negotiation_id=neg_id,
            sender="http://alice.local",
            our_price=100, their_price=140, proposed_price=120,
            action_taken="counter_offer", message_type="initial_proposal",
        )

        mock_exit = AsyncMock(return_value={"status": "ok"})

        with (
            patch.object(nthread_mod, "_thread_store", thread_store),
            patch("core.agent.app.utils.action_executor._negotiation_sessions", {}),
            patch("core.agent.app.utils.action_executor._negotiation_locks", {}),
            patch("core.agent.app.utils.action_executor.exit_negotiation", mock_exit),
        ):
            result = await TraderAgent._check_orphan(MagicMock(), event, ctx)

        assert result is not None
        mock_exit.assert_called_once()
