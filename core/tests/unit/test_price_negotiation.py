"""Parametrized price negotiation tests for strategy-aware smart policies.

Tests the price_aware_decision (negotiation_action_price_interval_concession) policy.

STRATEGY-AWARE POLICY BEHAVIOR:

Minimizer (demanding compute, our_price = ceiling/max willing to pay):
- Accepts if their_price <= our_price (favorable - at or below ceiling)
- Counters if our_price < their_price <= 1.5x our_price (above ceiling but reasonable)
- Exits if their_price > 1.5x our_price (unreasonable)

Maximizer (offering compute, our_price = floor/min willing to accept):
- Accepts if their_price >= our_price (favorable - at or above floor)
- Counters if 0.67x our_price <= their_price < our_price (below floor but reasonable)
- Exits if their_price < 0.67x our_price (unreasonable)

NOTE: Policy requires strategy to be specified. If no strategy, passes to next policy.
"""

import pytest
from core.agent.app.schema.pydantic_models import DecisionContext, NegotiationEvent
from core.agent.app.policy.store import PolicyStore
from core.agent.app.utils.sqlite_client import SQLiteClient
from core.agent.app.policy.evaluator import CallableEvaluator
import tempfile
import os


@pytest.fixture
def temp_db():
    """Create a temporary database file for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def policy_store(temp_db):
    """Create a PolicyStore with registered policies for testing."""
    from core.agent.app.policy.registry import CALLABLE_REGISTRY

    # Clear registry to ensure clean state
    CALLABLE_REGISTRY.clear()

    # Import policies to register them via @policy_callable decorator
    from domain.compute.agent.app.policy.store import (
        negotiation_action_price_interval_concession,
        negotiation_action_safe_default_reject,
    )

    # Create policy store
    sqlite_client = SQLiteClient(db_path=temp_db)
    store = PolicyStore(sqlite_client=sqlite_client)

    # Register callables from the module-level registry
    store.register_callables({
        "negotiation.action.price_interval_concession": negotiation_action_price_interval_concession,
        "negotiation.action.safe_default_reject": negotiation_action_safe_default_reject,
    })

    yield store

    # Cleanup
    CALLABLE_REGISTRY.clear()


def create_test_context(
    *,
    our_price: int | None,
    their_price: int | None,  # This is what they propose (transmitted as proposed_price)
    strategy: str | None,
    negotiation_id: str = "test_negotiation",
    event_id: str = "evt_test",
    agent_id: str = "test_agent",
    our_order_id: str = "order_our",
    their_order_id: str = "order_their",
    negotiation_history: list | None = None,
) -> DecisionContext:
    """Create a test context with POV-neutral structure.
    
    This helper properly separates:
    - transmitted data: proposed_price (what they're offering)
    - local POV data: our_initial_price, our_strategy (stored locally, never transmitted)
    
    The policy looks up our_initial_price and our_strategy from market_state.thread_info,
    and interprets proposed_price as their_price.
    """
    event = NegotiationEvent.create(
        event_id=event_id,
        negotiation_id=negotiation_id,
        message_type="counter_proposal",
        sender="other_agent",
        data={
            "proposed_price": their_price,  # What they're proposing
        }
    )
    
    return DecisionContext(
        event=event,
        agent_id=agent_id,
        available_resources={},
        market_state={
            "thread_info": {
                "our_initial_price": our_price,
                "our_strategy": strategy,
            }
        },
        negotiation_history=negotiation_history or []
    )


class TestMinimizerStrategy:
    """Test minimizer strategy (demanding compute, offering tokens)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("our_price,their_price,expected_action,reason", [
        # Minimizer accepts if their_price <= our_price (favorable - at or below ceiling)
        (100, 50, "accept_offer", "well below ceiling"),
        (100, 80, "accept_offer", "below ceiling"),
        (100, 90, "accept_offer", "below ceiling"),
        (100, 100, "accept_offer", "at ceiling"),
        (100, 110, "counter_offer", "above ceiling - should counter"),
        (100, 150, "counter_offer", "at 1.5x boundary - counter"),
        (100, 151, "exit_negotiation", "beyond 1.5x - exit"),
        (100, 200, "exit_negotiation", "way beyond - exit"),
    ])
    async def test_minimizer_decisions(self, policy_store, our_price, their_price, expected_action, reason):
        """Test minimizer strategy at various price points."""
        context = create_test_context(
            our_price=our_price,
            their_price=their_price,
            strategy="minimize",
            negotiation_id=f"test_minimizer_{our_price}_{their_price}",
            event_id=f"evt_test_minimizer_{our_price}_{their_price}",
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        assert func is not None, "Policy not registered"

        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        assert result is not None, f"Policy returned None for: our={our_price}, their={their_price}, reason={reason}"
        assert result.action_type.value == expected_action, \
            f"Expected {expected_action}, got {result.action_type.value} for: our={our_price}, their={their_price}, reason={reason}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("our_price,their_price,expected_action", [
        # Minimizer: accept if <= our_price
        (100, 100, "accept_offer"),   # At ceiling - accept
        (100, 80, "accept_offer"),    # Below ceiling - accept
        (100, 50, "accept_offer"),    # Well below - accept
        (100, 0, "accept_offer"),     # Zero - accept (edge case)
        # Minimizer: counter if our_price < their_price <= 1.5x
        (100, 110, "counter_offer"),  # Above ceiling, reasonable
        (100, 140, "counter_offer"),  # Above ceiling, still reasonable
        (100, 150, "counter_offer"),  # At 1.5x boundary - counter
        # Minimizer: exit if > 1.5x
        (100, 151, "exit_negotiation"),  # Beyond 1.5x - exit
        (100, 200, "exit_negotiation"),  # Way beyond - exit
        (100, 1000, "exit_negotiation"), # Extreme - exit
    ])
    async def test_minimizer_complete_coverage(self, policy_store, our_price, their_price, expected_action):
        """Test minimizer strategy with complete coverage of all cases."""
        context = create_test_context(
            our_price=our_price,
            their_price=their_price,
            strategy="minimize",
            negotiation_id=f"test_min_{our_price}_{their_price}",
            event_id=f"evt_test_min_{our_price}_{their_price}",
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        assert result is not None
        assert result.action_type.value == expected_action

    @pytest.mark.asyncio
    async def test_minimizer_counter_calculation(self, policy_store):
        """Test minimizer counter-offer price calculation (midpoint)."""
        context = create_test_context(
            our_price=100,
            their_price=140,
            strategy="minimize",
            negotiation_id="test_minimizer_counter",
            event_id="evt_test_minimizer_counter",
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        # With clamping: min(100, (100 + 140) // 2) = min(100, 120) = 100
        assert result is not None
        assert result.action_type.value == "counter_offer"
        assert result.parameters.get("proposed_price") == 100


class TestMaximizerStrategy:
    """Test maximizer strategy (offering compute, demanding tokens)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("our_price,their_price,expected_action", [
        # Maximizer: accept if their_price >= our_price
        (100, 100, "accept_offer"),   # At floor - accept
        (100, 120, "accept_offer"),   # Above floor - accept
        (100, 200, "accept_offer"),   # Well above - accept
        (100, 1000, "accept_offer"),  # Extreme - accept
        # Maximizer: counter if 0.67x <= their_price < our_price (where 0.67 ≈ 1/1.5)
        (100, 90, "counter_offer"),   # Below floor, reasonable
        (100, 70, "counter_offer"),   # Below floor, still reasonable
        (100, 67, "counter_offer"),   # At 1/1.5 boundary - counter
        # Maximizer: exit if < 0.67x
        (100, 66, "exit_negotiation"),  # Beyond boundary - exit
        (100, 50, "exit_negotiation"),  # Way below - exit
        (100, 0, "exit_negotiation"),   # Zero - exit
    ])
    async def test_maximizer_decisions(self, policy_store, our_price, their_price, expected_action):
        """Test maximizer strategy at various price points."""
        context = create_test_context(
            our_price=our_price,
            their_price=their_price,
            strategy="maximize",
            negotiation_id=f"test_maximizer_{our_price}_{their_price}",
            event_id=f"evt_test_maximizer_{our_price}_{their_price}",
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        assert result is not None, f"Policy returned None for: our={our_price}, their={their_price}"
        assert result.action_type.value == expected_action, \
            f"Expected {expected_action}, got {result.action_type.value} for: our={our_price}, their={their_price}"

    @pytest.mark.asyncio
    async def test_maximizer_counter_calculation(self, policy_store):
        """Test maximizer counter-offer price calculation (midpoint)."""
        context = create_test_context(
            our_price=100,
            their_price=70,
            strategy="maximize",
            negotiation_id="test_maximizer_counter",
            event_id="evt_test_maximizer_counter",
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        # With clamping: max(100, (100 + 70) // 2) = max(100, 85) = 100
        assert result is not None
        assert result.action_type.value == "counter_offer"
        assert result.parameters.get("proposed_price") == 100


class TestNegotiationScenarios:
    """Test realistic negotiation scenarios."""

    @pytest.mark.asyncio
    async def test_no_strategy_passes_to_next_policy(self, policy_store):
        """Test that policy passes to next policy when no strategy is specified."""
        event = NegotiationEvent.create(
            event_id="evt_test_no_strategy",
            negotiation_id="test_no_strategy",
            message_type="counter_proposal",
            sender="other_agent",
            data={
                "our_price": 100,
                "their_price": 110,
                "our_order_id": "order_our",
                "their_order_id": "order_their",
                # No strategy specified
            }
        )

        context = DecisionContext(
            event=event,
            agent_id="test_agent",
            available_resources={},
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        # Should return None (pass to next policy) when no strategy specified
        assert result is None, "Policy should pass to next policy when no strategy is specified"

    @pytest.mark.asyncio
    async def test_minimizer_maximizer_equilibrium(self, policy_store):
        """Test that minimizer and maximizer reach equilibrium at same price.

        Minimizer at 100 (ceiling) receives offer at 110 → counters (110 > 100)
        Maximizer at 100 (floor) receives offer at 110 → accepts (110 >= 100)
        """
        # Minimizer perspective (ceiling=100, sees 110)
        minimizer_context = create_test_context(
            our_price=100,
            their_price=110,
            strategy="minimize",
            agent_id="minimizer_agent",
            negotiation_id="test_eq",
            event_id="evt_test_min_eq",
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        minimizer_result = await ce.evaluate(minimizer_context)

        # Maximizer perspective (floor=100, sees 110)
        maximizer_context = create_test_context(
            our_price=100,
            their_price=110,
            strategy="maximize",
            agent_id="maximizer_agent",
            negotiation_id="test_eq",
            event_id="evt_test_max_eq",
        )

        maximizer_result = await ce.evaluate(maximizer_context)

        # Maximizer should accept at 110 (>= floor)
        assert maximizer_result.action_type.value == "accept_offer"
        # Minimizer should counter at 110 (above ceiling but <= 1.5x)
        assert minimizer_result.action_type.value == "counter_offer"

    @pytest.mark.asyncio
    async def test_minimizer_maximizer_counter_convergence(self, policy_store):
        """Test that minimizer and maximizer counter-offers converge toward equilibrium.

        Initial: Minimizer at 100, Maximizer at 100
        Offer: 140 (above minimizer's ceiling)
        Expected: Minimizer counters to 100 (clamped to ceiling), Maximizer accepts (100 >= 100)
        """
        # Minimizer sees 140 → counters to 100 (clamped: min(100, (100+140)//2) = 100)
        minimizer_context = create_test_context(
            our_price=100,
            their_price=140,
            strategy="minimize",
            agent_id="minimizer_agent",
            negotiation_id="test_conv",
            event_id="evt_test_min_conv",
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        minimizer_result = await ce.evaluate(minimizer_context)

        # Minimizer should counter to 100 (clamped to ceiling)
        assert minimizer_result.action_type.value == "counter_offer"
        assert minimizer_result.parameters.get("proposed_price") == 100

        # Maximizer sees 100 (from minimizer counter, clamped) → should accept (>= floor)
        maximizer_context = create_test_context(
            our_price=100,
            their_price=100,
            strategy="maximize",
            agent_id="maximizer_agent",
            negotiation_id="test_conv",
            event_id="evt_test_max_conv",
        )

        maximizer_result = await ce.evaluate(maximizer_context)

        # Maximizer should accept at 100 (>= floor of 100)
        assert maximizer_result.action_type.value == "accept_offer"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("our_price,their_price,expected_reason", [
        (None, 100, "missing_price_data"),
        (100, None, "missing_price_data"),
        (100, "invalid", "invalid_price_types"),
        ("invalid", 100, "invalid_price_types"),
        (0, 100, "non_positive_prices"),
        (100, 0, "non_positive_prices"),
        (-50, 100, "non_positive_prices"),
        (100, -50, "non_positive_prices"),
    ])
    async def test_safe_default_reject(self, policy_store, our_price, their_price, expected_reason):
        """Test safe default policy rejects on invalid price data."""
        event = NegotiationEvent.create(
            event_id=f"evt_test_invalid_{our_price}_{their_price}",
            negotiation_id=f"test_invalid_{our_price}_{their_price}",
            message_type="counter_proposal",
            sender="other_agent",
            data={
                "proposed_price": their_price,
            }
        )

        context = DecisionContext(
            event=event,
            agent_id="test_agent",
            available_resources={},
            market_state={
                "thread_info": {
                    "our_initial_price": our_price,
                    "our_strategy": "minimize"
                }
            },
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.safe_default_reject")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        assert result is not None, "Safe default should always return an action"
        assert result.action_type.value == "reject_offer"
        assert result.parameters.get("reason") == expected_reason

    @pytest.mark.asyncio
    async def test_passes_to_next_policy_on_missing_data(self, policy_store):
        """Test that policy passes to next policy when price data is missing."""
        event = NegotiationEvent.create(
            event_id="evt_test_missing_data",
            negotiation_id="test_missing_data",
            message_type="counter_proposal",
            sender="other_agent",
            data={}
        )

        context = DecisionContext(
            event=event,
            agent_id="test_agent",
            available_resources={},
            market_state={
                 # Missing thread_info
                 "thread_info": {}
            },
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        # Should return None (pass to next policy) when price data missing
        assert result is None, "Policy should pass to next policy when price data missing"


class TestMultipleBilateralNegotiations:
    """Test scenarios with one agent negotiating with multiple counterparties.

    These tests verify that:
    1. An agent can maintain separate negotiations with different counterparties
    2. Each negotiation has isolated state (thread, round counter)
    3. Accepting one negotiation cancels competing negotiations
    4. Duplicate negotiations are prevented
    """

    @pytest.fixture
    def thread_store(self, temp_db):
        """Create a NegotiationThreadStore for multi-party tests."""
        from core.agent.app.policy.negotiation_thread import NegotiationThreadStore
        sqlite_client = SQLiteClient(db_path=temp_db)
        return NegotiationThreadStore(sqlite_client=sqlite_client)

    @pytest.mark.asyncio
    async def test_minimizer_negotiates_with_multiple_maximizers(self, policy_store, thread_store):
        """Agent A (minimizer) negotiates with Agents B and C (maximizers) independently.

        Scenario:
        - Agent A is a minimizer with order_A (ceiling=100)
        - Agent B is a maximizer with order_B (asking 150)
        - Agent C is a maximizer with order_C (asking 130)
        - A should counter both B and C, clamped to ceiling
        """
        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)

        # Create negotiation threads for A↔B and A↔C with our_initial_price and our_strategy
        await thread_store.create_thread(
            negotiation_id="order_A_order_B",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
            our_initial_price=100,
            our_strategy="minimize",
        )
        await thread_store.create_thread(
            negotiation_id="order_A_order_C",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
            owner_id="agent_A",
            our_initial_price=100,
            our_strategy="minimize",
        )

        # Agent A receives offer from Agent B (price 150)
        context_B = create_test_context(
            our_price=100,
            their_price=150,
            strategy="minimize",
            agent_id="agent_A",
            negotiation_id="order_A_order_B",
            event_id="evt_A_from_B",
        )

        # Agent A receives offer from Agent C (price 130)
        context_C = create_test_context(
            our_price=100,
            their_price=130,
            strategy="minimize",
            agent_id="agent_A",
            negotiation_id="order_A_order_C",
            event_id="evt_A_from_C",
        )

        # Evaluate both negotiations
        result_B = await ce.evaluate(context_B)
        result_C = await ce.evaluate(context_C)

        # Both should counter (150 and 130 are above ceiling of 100 but <= 1.5x)
        assert result_B.action_type.value == "counter_offer"
        assert result_C.action_type.value == "counter_offer"

        # Counter prices clamped to ceiling (our_price=100)
        assert result_B.parameters.get("proposed_price") == 100  # min(100, (100 + 150) // 2)
        assert result_C.parameters.get("proposed_price") == 100  # min(100, (100 + 130) // 2)

        # Record messages to threads
        await thread_store.add_message(
            negotiation_id="order_A_order_B",
            sender="agent_A",
            our_price=100,
            their_price=150,
            proposed_price=100,
            action_taken="COUNTER_OFFER",
            message_type="counter_proposal",
        )
        await thread_store.add_message(
            negotiation_id="order_A_order_C",
            sender="agent_A",
            our_price=100,
            their_price=130,
            proposed_price=100,
            action_taken="COUNTER_OFFER",
            message_type="counter_proposal",
        )

        # Verify threads are independent
        thread_B = await thread_store.get_thread("order_A_order_B")
        thread_C = await thread_store.get_thread("order_A_order_C")

        assert len(thread_B) == 1
        assert len(thread_C) == 1
        assert thread_B[0]["proposed_price"] == 100
        assert thread_C[0]["proposed_price"] == 100

    @pytest.mark.asyncio
    async def test_accept_cancels_competing_negotiations(self, policy_store, thread_store):
        """When A accepts B's offer, A's negotiation with C should be canceled.

        Scenario:
        - Agent A has active negotiations with B and C for order_A
        - B counters with price 100 (acceptable for minimizer A - at ceiling)
        - A accepts B's offer
        - Negotiation A↔C should be canceled
        """
        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)

        # Create both negotiation threads with our_initial_price and our_strategy
        await thread_store.create_thread(
            negotiation_id="order_A_order_B",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            our_initial_price=100,
            our_strategy="minimize",
            owner_id="agent_A",
        )
        await thread_store.create_thread(
            negotiation_id="order_A_order_C",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
            our_initial_price=100,
            our_strategy="minimize",
            owner_id="agent_A",
        )

        # Add some history to both threads
        await thread_store.add_message(
            negotiation_id="order_A_order_B",
            sender="agent_B",
            our_price=100,
            their_price=150,
            proposed_price=150,
            action_taken="COUNTER_OFFER",
            message_type="initial_proposal",
        )
        await thread_store.add_message(
            negotiation_id="order_A_order_C",
            sender="agent_C",
            our_price=100,
            their_price=140,
            proposed_price=140,
            action_taken="COUNTER_OFFER",
            message_type="initial_proposal",
        )

        # Agent B counters with 100 (acceptable for minimizer A - at ceiling)
        context = create_test_context(
            our_price=100,
            their_price=100,
            strategy="minimize",
            agent_id="agent_A",
            negotiation_id="order_A_order_B",
            event_id="evt_A_accept_B",
        )

        result = await ce.evaluate(context)
        assert result.action_type.value == "accept_offer"

        # Simulate accept_offer action: cancel competing negotiations
        canceled = await thread_store._sqlite.cancel_negotiations_for_order(
            order_id="order_A",
            except_negotiation_id="order_A_order_B",
        )

        # Verify A↔C was canceled (cancel_negotiations_for_order returns list of dicts)
        canceled_ids = [entry["negotiation_id"] for entry in canceled]
        assert "order_A_order_C" in canceled_ids

        # Verify A↔B is still active (not canceled)
        thread_B = await thread_store.get_thread("order_A_order_B")
        assert len(thread_B) == 1  # Still has messages

        # Verify canceled thread is marked
        active_negs = await thread_store._sqlite.get_active_negotiations_for_order(
            order_id="order_A"
        )
        active_neg_ids = [n["negotiation_id"] for n in active_negs]

        # Only A↔B should be active (if not yet marked terminal)
        # A↔C should be canceled
        assert "order_A_order_C" not in active_neg_ids

    @pytest.mark.asyncio
    async def test_independent_thread_tracking(self, thread_store):
        """Each negotiation has its own thread with isolated round counters.

        Verifies that round numbers increment independently per negotiation.
        """
        # Create two threads
        await thread_store.create_thread(
            negotiation_id="neg_1",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
        )
        await thread_store.create_thread(
            negotiation_id="neg_2",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
            owner_id="agent_A",
        )

        # Add 3 messages to neg_1
        for i in range(3):
            round_num = await thread_store.add_message(
                negotiation_id="neg_1",
                sender=f"agent_{'A' if i % 2 == 0 else 'B'}",
                our_price=100,
                their_price=120,
                proposed_price=110,
                action_taken="COUNTER_OFFER",
                message_type="counter_proposal",
            )
            assert round_num == i, f"neg_1 round should be {i}, got {round_num}"

        # Add 1 message to neg_2
        round_num = await thread_store.add_message(
            negotiation_id="neg_2",
            sender="agent_C",
            our_price=100,
            their_price=130,
            proposed_price=130,
            action_taken="COUNTER_OFFER",
            message_type="initial_proposal",
        )
        assert round_num == 0, "neg_2 should start at round 0"

        # Add another message to neg_2
        round_num = await thread_store.add_message(
            negotiation_id="neg_2",
            sender="agent_A",
            our_price=100,
            their_price=130,
            proposed_price=115,
            action_taken="COUNTER_OFFER",
            message_type="counter_proposal",
        )
        assert round_num == 1, "neg_2 should be at round 1"

        # Verify thread lengths are independent
        thread_1 = await thread_store.get_thread("neg_1")
        thread_2 = await thread_store.get_thread("neg_2")

        assert len(thread_1) == 3
        assert len(thread_2) == 2

        # Verify round numbers
        assert [m["round"] for m in thread_1] == [0, 1, 2]
        assert [m["round"] for m in thread_2] == [0, 1]

    @pytest.mark.asyncio
    async def test_duplicate_negotiation_prevention(self, thread_store):
        """Duplicate negotiations between same order pair should be detected.

        Verifies check_existing_negotiation() prevents creating duplicates.
        """
        # Create first negotiation
        await thread_store.create_thread(
            negotiation_id="order_A_order_B",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
        )

        # Check for existing negotiation (same order pair)
        existing = await thread_store._sqlite.check_existing_negotiation(
            our_order_id="order_A",
            their_order_id="order_B",
        )

        assert existing is not None
        assert existing["negotiation_id"] == "order_A_order_B"

        # Check reverse direction (should also find it)
        existing_reverse = await thread_store._sqlite.check_existing_negotiation(
            our_order_id="order_B",
            their_order_id="order_A",
        )

        # Should find the same negotiation (bidirectional check)
        assert existing_reverse is not None

        # Check non-existing pair
        non_existing = await thread_store._sqlite.check_existing_negotiation(
            our_order_id="order_A",
            their_order_id="order_D",
        )
        assert non_existing is None

    @pytest.mark.asyncio
    async def test_multi_round_convergence_with_multiple_maximizers(self, policy_store, thread_store):
        """Test multi-round negotiation where minimizer converges with one maximizer.

        Scenario:
        - Round 1: Minimizer A counters Maximizers B (150→125) and C (130→115)
        - Round 2: Both B and C accept (125 >= 100 and 115 >= 100, both acceptable for maximizers)
        - A accepts whichever completes first, cancels the other
        """
        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)

        # Setup threads
        await thread_store.create_thread(
            negotiation_id="A_B",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
            our_initial_price=100,
            our_strategy="minimize",
        )
        await thread_store.create_thread(
            negotiation_id="A_C",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
            owner_id="agent_A",
            our_initial_price=100,
            our_strategy="minimize",
        )

        # Round 1: Both maximizers offer high prices
        # A counters both
        for neg_id, their_price, expected_counter in [
            ("A_B", 150, 125),
            ("A_C", 130, 115),
        ]:
            await thread_store.add_message(
                negotiation_id=neg_id,
                sender="agent_A",
                our_price=100,
                their_price=their_price,
                proposed_price=expected_counter,
                action_taken="COUNTER_OFFER",
                message_type="counter_proposal",
            )

        # Round 2: B accepts A's counter of 125 (>= floor of 100), C accepts A's counter of 115 (>= floor)
        # Check B's acceptance of 125
        context_B_r2 = create_test_context(
            our_price=100,  # B's floor (maximizer offering compute)
            their_price=125,  # A's counter
            strategy="maximize",
            agent_id="agent_B",
            negotiation_id="A_B",
            event_id="evt_B_r2",
        )

        result_B = await ce.evaluate(context_B_r2)
        # 125 >= 100 (floor), maximizer should accept
        assert result_B.action_type.value == "accept_offer"

        # Check C's acceptance of 115
        context_C_r2 = create_test_context(
            our_price=100,  # C's floor (maximizer offering compute)
            their_price=115,  # A's counter
            strategy="maximize",
            agent_id="agent_C",
            negotiation_id="A_C",
            event_id="evt_C_r2",
        )

        result_C = await ce.evaluate(context_C_r2)
        # 115 >= 100 (floor), maximizer should accept
        assert result_C.action_type.value == "accept_offer"

        # Now A accepts B, which should cancel C
        canceled = await thread_store._sqlite.cancel_negotiations_for_order(
            order_id="order_A",
            except_negotiation_id="A_B",
        )

        canceled_ids = [entry["negotiation_id"] for entry in canceled]
        assert "A_C" in canceled_ids

    @pytest.mark.asyncio
    async def test_maximizer_negotiates_with_multiple_minimizers(self, policy_store, thread_store):
        """Agent A (maximizer) negotiates with Agents B and C (minimizers) independently.

        Scenario:
        - Agent A is a maximizer with order_A (floor=100)
        - Agent B is a minimizer with order_B (offering 70)
        - Agent C is a minimizer with order_C (offering 90)
        - A should counter both B and C (both offers below floor but >= 0.67x)
        """
        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)

        # Agent A (maximizer) receives offer from Agent B (price 70)
        context_B = create_test_context(
            our_price=100,
            their_price=70,
            strategy="maximize",
            agent_id="agent_A",
            negotiation_id="order_A_order_B",
            event_id="evt_A_from_B_max",
        )

        # Agent A (maximizer) receives offer from Agent C (price 90)
        context_C = create_test_context(
            our_price=100,
            their_price=90,
            strategy="maximize",
            agent_id="agent_A",
            negotiation_id="order_A_order_C",
            event_id="evt_A_from_C_max",
        )

        result_B = await ce.evaluate(context_B)
        result_C = await ce.evaluate(context_C)

        # B's offer of 70 is below floor (100), but >= 0.67x (67), so maximizer should counter
        assert result_B.action_type.value == "counter_offer"
        assert result_B.parameters.get("proposed_price") == 100  # max(100, (100 + 70) // 2)

        # C's offer of 90 is below floor (100), but >= 0.67x (67), so maximizer should counter
        # Wait, 90 < 100, so maximizer should counter (not accept)
        assert result_C.action_type.value == "counter_offer"


class TestMakeOfferRoundGuard:
    """Tests for the round guard injected into negotiation_respond_to_make_offer.

    The guard prevents infinite 7↔8 oscillation (Scenario B: no ZOPA, prices within 1.5x band)
    by counting our own COUNTER_OFFER messages in the thread and exiting when stale or exhausted.
    """

    OUR_URL = "http://alice.local"
    OUR_ORDER_ID = "order-zzz-alice"   # sorts AFTER "order-aaa-bob" → canonical guard skipped
    THEIR_ORDER_ID = "order-aaa-bob"   # sorts FIRST → not canonical initiator

    @pytest.fixture
    def thread_store(self, temp_db):
        from core.agent.app.policy.negotiation_thread import NegotiationThreadStore
        return NegotiationThreadStore(SQLiteClient(db_path=temp_db))

    def _make_event_and_context(self, their_price: int = 150):
        """Build a MakeOfferEvent + DecisionContext for the incoming offer."""
        from core.agent.app.schema.pydantic_models import (
            MakeOfferEvent, MarketOrder, ComputeResource, TokenResource,
            ERC20TokenMetadata, GPUModel, Region, DecisionContext,
        )
        token = ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6)
        their_order = MarketOrder(
            order_id=self.THEIR_ORDER_ID,
            order_maker="http://bob.local",
            offer_resource=TokenResource(token=token, amount=their_price),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            duration_hours=1,
        )
        event = MakeOfferEvent(event_id="evt_test_guard", source="http://bob.local", order=their_order)
        context = DecisionContext(event=event, agent_id=self.OUR_URL, available_resources={})
        return event, context

    def _our_order_dict(self, our_price: int = 100):
        """Build our maximizer order as a dict (seller offering compute, demanding tokens)."""
        from core.agent.app.schema.pydantic_models import (
            MarketOrder, ComputeResource, TokenResource, ERC20TokenMetadata, GPUModel, Region,
        )
        token = ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6)
        order = MarketOrder(
            order_id=self.OUR_ORDER_ID,
            order_maker=self.OUR_URL,
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(token=token, amount=our_price),
            duration_hours=1,
        )
        return order.model_dump(mode="json")

    @pytest.mark.asyncio
    async def test_make_offer_exits_at_max_rounds(self, thread_store, temp_db):
        """Round guard exits with EXIT_NEGOTIATION / max_rounds after MAX_ROUNDS counter-offers."""
        from unittest.mock import AsyncMock, patch
        from core.agent.app.policy.action_builders import make_negotiation_id
        import core.agent.app.utils.config as cfg_mod
        from domain.compute.agent.app.policy.store import negotiation_respond_to_make_offer

        neg_id = make_negotiation_id(self.OUR_ORDER_ID, self.THEIR_ORDER_ID)

        # Seed thread with 10 counter-offers from our agent (= MAX_ROUNDS)
        for i in range(10):
            await thread_store.add_message(
                negotiation_id=neg_id,
                sender=self.OUR_URL,
                our_price=100,
                their_price=150,
                proposed_price=120 - i,
                action_taken="counter_offer",
                message_type="counter_proposal",
            )

        _, context = self._make_event_and_context(their_price=150)
        our_order = self._our_order_dict(our_price=100)

        original_base_url = cfg_mod.CONFIG.base_url_override
        try:
            object.__setattr__(cfg_mod.CONFIG, "base_url_override", self.OUR_URL)
            with (
                patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_reg,
                patch("domain.compute.agent.app.policy.store.get_thread_store", return_value=thread_store),
            ):
                mock_client = AsyncMock()
                mock_client.query_orders = AsyncMock(return_value=[our_order])
                mock_reg.return_value = mock_client

                result = await negotiation_respond_to_make_offer(context)
        finally:
            object.__setattr__(cfg_mod.CONFIG, "base_url_override", original_base_url)

        assert result is not None
        assert result.action_type.value == "exit_negotiation"
        assert result.parameters.get("reason") == "max_rounds"

    @pytest.mark.asyncio
    async def test_make_offer_exits_on_stale_price(self, thread_store, temp_db):
        """Round guard exits with EXIT_NEGOTIATION / stale_negotiation when last 2 counters have same price."""
        from unittest.mock import AsyncMock, patch
        from core.agent.app.policy.action_builders import make_negotiation_id
        from domain.compute.agent.app.policy.store import negotiation_respond_to_make_offer

        neg_id = make_negotiation_id(self.OUR_ORDER_ID, self.THEIR_ORDER_ID)

        # Two counter-offers from our agent, both at proposed_price=7 (the oscillation case)
        for _ in range(2):
            await thread_store.add_message(
                negotiation_id=neg_id,
                sender=self.OUR_URL,
                our_price=8,
                their_price=7,
                proposed_price=7,
                action_taken="counter_offer",
                message_type="counter_proposal",
            )

        _, context = self._make_event_and_context(their_price=7)
        our_order = self._our_order_dict(our_price=8)

        import core.agent.app.utils.config as cfg_mod
        original_base_url = cfg_mod.CONFIG.base_url_override
        try:
            object.__setattr__(cfg_mod.CONFIG, "base_url_override", self.OUR_URL)
            with (
                patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_reg,
                patch("domain.compute.agent.app.policy.store.get_thread_store", return_value=thread_store),
            ):
                mock_client = AsyncMock()
                mock_client.query_orders = AsyncMock(return_value=[our_order])
                mock_reg.return_value = mock_client

                result = await negotiation_respond_to_make_offer(context)
        finally:
            object.__setattr__(cfg_mod.CONFIG, "base_url_override", original_base_url)

        assert result is not None
        assert result.action_type.value == "exit_negotiation"
        assert result.parameters.get("reason") == "stale_negotiation"
