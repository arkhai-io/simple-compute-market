"""Tests for PE Audit negotiation flow fixes (C1, C2, C3, H1, H2, M1).

These tests verify each audit fix in isolation:
- C3: update_negotiation_thread_terminal sets status='terminated'
- H1: get_thread_info includes terminal_state; bounded_rounds guards terminated threads
- C1: respond_to_make_offer filters by order_maker (covered in test_incoming_offer_handling)
- H2: counter_offer fails early on invalid counterparty URL
- M1: _resources_are_complementary rejects non-complementary orders
"""

import pytest
import tempfile
import os
from unittest.mock import AsyncMock, patch, MagicMock

from app.utils.sqlite_client import SQLiteClient
from app.policies.negotiation_thread import NegotiationThreadStore
from app.policies.store import (
    _resources_are_complementary,
    negotiation_guard_bounded_rounds_and_timeout,
)
from app.schema.pydantic_models import (
    DecisionContext,
    NegotiationEvent,
    ActionType,
    MarketOrder,
    ComputeResource,
    TokenResource,
    ERC20TokenMetadata,
    GPUModel,
    Region,
)


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def sqlite_client(temp_db):
    return SQLiteClient(db_path=temp_db)


@pytest.fixture
def thread_store(sqlite_client):
    return NegotiationThreadStore(sqlite_client=sqlite_client)


# =============================================================================
# C3: update_negotiation_thread_terminal sets status='terminated'
# =============================================================================
class TestC3TerminalStatusUpdate:
    """C3: Marking a thread terminal must also set status='terminated'."""

    @pytest.mark.asyncio
    async def test_terminal_sets_status_terminated(self, sqlite_client):
        """After mark_terminal, status should be 'terminated' not 'active'."""
        await sqlite_client.create_negotiation_thread(
            negotiation_id="neg_c3",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
            status="active",
        )

        # Mark as terminal
        await sqlite_client.update_negotiation_thread_terminal(
            negotiation_id="neg_c3",
            terminal_state="failure",
        )

        # Verify status is 'terminated', not still 'active'
        info = await sqlite_client.get_thread_info(
            negotiation_id="neg_c3",
            owner_id="agent_A",
        )
        assert info is not None
        assert info["terminal_state"] == "failure"
        assert info["status"] == "terminated"

    @pytest.mark.asyncio
    async def test_terminated_thread_not_in_active_queries(self, sqlite_client):
        """Terminated threads must NOT appear in active negotiation queries."""
        await sqlite_client.create_negotiation_thread(
            negotiation_id="neg_c3_active",
            our_order_id="order_X",
            their_order_id="order_Y",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
            status="active",
        )

        # Mark terminal
        await sqlite_client.update_negotiation_thread_terminal(
            negotiation_id="neg_c3_active",
            terminal_state="success",
        )

        # check_existing_negotiation should NOT find it (it filters status='active')
        existing = await sqlite_client.check_existing_negotiation(
            our_order_id="order_X",
            their_order_id="order_Y",
        )
        assert existing is None, "Terminated negotiation should not appear as active"

    @pytest.mark.asyncio
    async def test_terminated_thread_not_in_active_for_order(self, sqlite_client):
        """get_active_negotiations_for_order should not return terminated threads."""
        await sqlite_client.create_negotiation_thread(
            negotiation_id="neg_c3_order",
            our_order_id="order_P",
            their_order_id="order_Q",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
            status="active",
        )

        await sqlite_client.update_negotiation_thread_terminal(
            negotiation_id="neg_c3_order",
            terminal_state="failure",
        )

        active = await sqlite_client.get_active_negotiations_for_order(order_id="order_P")
        assert len(active) == 0, "Terminated negotiation should not appear in active list"


# =============================================================================
# H1: get_thread_info includes terminal_state + bounded_rounds terminal guard
# =============================================================================
class TestH1TerminalStateInThreadInfo:
    """H1: get_thread_info must include terminal_state field."""

    @pytest.mark.asyncio
    async def test_thread_info_includes_terminal_state(self, sqlite_client):
        """terminal_state field must be present in get_thread_info result."""
        await sqlite_client.create_negotiation_thread(
            negotiation_id="neg_h1",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
        )

        info = await sqlite_client.get_thread_info(
            negotiation_id="neg_h1",
            owner_id="agent_A",
        )
        assert info is not None
        assert "terminal_state" in info
        assert info["terminal_state"] is None  # Not yet terminated

    @pytest.mark.asyncio
    async def test_thread_info_reflects_terminal_state_after_update(self, sqlite_client):
        """After marking terminal, get_thread_info should show the terminal_state."""
        await sqlite_client.create_negotiation_thread(
            negotiation_id="neg_h1_term",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
        )

        await sqlite_client.update_negotiation_thread_terminal(
            negotiation_id="neg_h1_term",
            terminal_state="success",
        )

        info = await sqlite_client.get_thread_info(
            negotiation_id="neg_h1_term",
            owner_id="agent_A",
        )
        assert info["terminal_state"] == "success"


class TestH1TerminalGuardInBoundedRounds:
    """H1: bounded_rounds_and_timeout must reject events on terminated threads."""

    @pytest.mark.asyncio
    async def test_terminated_thread_exits_immediately(self):
        """Counter-offer on a terminated thread should EXIT immediately."""
        event = NegotiationEvent.create(
            event_id="evt_h1",
            negotiation_id="neg_terminated",
            message_type="counter_proposal",
            sender="other_agent",
            data={"proposed_price": 100},
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={
                "thread_info": {
                    "terminal_state": "failure",
                    "our_initial_price": 100,
                    "our_strategy": "minimize",
                }
            },
        )

        result = negotiation_guard_bounded_rounds_and_timeout(context)
        assert result is not None
        assert result.action_type == ActionType.EXIT_NEGOTIATION
        assert "already_terminated" in result.parameters.get("reason", "")

    @pytest.mark.asyncio
    async def test_active_thread_passes_through(self):
        """Counter-offer on an active thread should NOT be rejected by guard."""
        event = NegotiationEvent.create(
            event_id="evt_h1_active",
            negotiation_id="neg_active",
            message_type="counter_proposal",
            sender="other_agent",
            data={"proposed_price": 100},
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={
                "thread_info": {
                    "terminal_state": None,
                    "our_initial_price": 100,
                    "our_strategy": "minimize",
                }
            },
            negotiation_history=[],
        )

        result = negotiation_guard_bounded_rounds_and_timeout(context)
        # Should return None (pass through to next policy), not EXIT
        assert result is None


# =============================================================================
# H2: counter_offer fails early on invalid URL
# =============================================================================
class TestH2CounterOfferURLValidation:
    """H2: counter_offer must fail early when counterparty URL is invalid."""

    @pytest.mark.asyncio
    async def test_counter_offer_rejects_non_url_order_maker(self):
        """counter_offer should error when order_maker is not a URL."""
        from app.utils.action_executor import counter_offer

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test_inv"
        mock_ctx.branch = "main"

        with patch("app.utils.action_executor.get_registry_client") as mock_reg:
            mock_client = AsyncMock()
            mock_client.get_order = AsyncMock(return_value={
                "order_id": "order_123",
                "order_maker": "onchain_hash_not_a_url",  # Invalid: not http(s)
            })
            mock_reg.return_value = mock_client

            result = await counter_offer(
                ctx=mock_ctx,
                parameters={
                    "negotiation_id": "neg_h2",
                    "order_id": "order_123",
                    "proposed_price": 100,
                    "our_price": 90,
                    "their_price": 110,
                },
            )

        assert result["status"] == "error"
        assert "invalid counterparty URL" in result["message"]

    @pytest.mark.asyncio
    async def test_counter_offer_rejects_missing_order_maker(self):
        """counter_offer should error when order_maker is missing."""
        from app.utils.action_executor import counter_offer

        mock_ctx = MagicMock()
        mock_ctx.invocation_id = "test_inv"
        mock_ctx.branch = "main"

        with patch("app.utils.action_executor.get_registry_client") as mock_reg:
            mock_client = AsyncMock()
            mock_client.get_order = AsyncMock(return_value={
                "order_id": "order_456",
                # order_maker is missing
            })
            mock_reg.return_value = mock_client

            result = await counter_offer(
                ctx=mock_ctx,
                parameters={
                    "negotiation_id": "neg_h2_missing",
                    "order_id": "order_456",
                    "proposed_price": 100,
                    "our_price": 90,
                    "their_price": 110,
                },
            )

        assert result["status"] == "error"
        assert "invalid counterparty URL" in result["message"]


# =============================================================================
# M1: _resources_are_complementary
# =============================================================================
class TestM1ResourceCompatibility:
    """M1: _resources_are_complementary must verify resource type matching."""

    def test_complementary_compute_token_pair(self):
        """Compute-offer vs Token-offer should be complementary."""
        our_order = {
            "offer_resource": {"gpu_model": "H200", "quantity": 1},
            "demand_resource": {"token": "MOCK", "amount": 100},
        }
        their_order = {
            "offer_resource": {"token": "MOCK", "amount": 80},
            "demand_resource": {"gpu_model": "H200", "quantity": 1},
        }
        assert _resources_are_complementary(our_order, their_order) is True

    def test_same_direction_not_complementary(self):
        """Both offering compute should NOT be complementary."""
        our_order = {
            "offer_resource": {"gpu_model": "H200", "quantity": 1},
            "demand_resource": {"token": "MOCK", "amount": 100},
        }
        their_order = {
            "offer_resource": {"gpu_model": "V100", "quantity": 2},
            "demand_resource": {"token": "MOCK", "amount": 50},
        }
        assert _resources_are_complementary(our_order, their_order) is False

    def test_both_offering_tokens_not_complementary(self):
        """Both offering tokens should NOT be complementary."""
        our_order = {
            "offer_resource": {"token": "MOCK", "amount": 100},
            "demand_resource": {"gpu_model": "H200", "quantity": 1},
        }
        their_order = {
            "offer_resource": {"token": "USDC", "amount": 50},
            "demand_resource": {"gpu_model": "V100", "quantity": 1},
        }
        assert _resources_are_complementary(our_order, their_order) is False

    def test_empty_resources_vacuously_complementary(self):
        """Empty resources are vacuously complementary (both non-compute).

        This can't happen in practice because determine_strategy_from_order
        gates the call — but the function treats "no resources" as "token-like".
        """
        assert _resources_are_complementary({}, {}) is True
