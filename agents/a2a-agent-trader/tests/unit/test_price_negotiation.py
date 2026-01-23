"""Parametrized price negotiation tests for role-aware smart policies.

Tests the price_aware_decision (negotiation_action_price_interval_concession) policy.

ROLE-AWARE POLICY BEHAVIOR:

Buyer (demanding compute, our_price = max willing to pay):
- Accepts if 50% <= their_price <= 120% of our_price (reasonable range)
- Counters if 120% < their_price <= 200% of our_price (high but reasonable)
- Exits if their_price < 50% or > 200% of our_price

Seller (offering compute, our_price = min willing to accept):
- Accepts if 80% <= their_price <= 200% of our_price (reasonable range)
- Counters if 50% <= their_price < 80% of our_price (low but reasonable)
- Exits if their_price < 50% or > 200% of our_price

NOTE: Policy requires role to be specified. If no role, passes to next policy.
"""

import pytest
from app.schema.pydantic_models import DecisionContext, NegotiationEvent
from app.policies.store import PolicyStore
from app.policies.sqlite_client import SQLiteClient
from app.policies.evaluator import CallableEvaluator
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
    from app.policies.registry import CALLABLE_REGISTRY

    # Clear registry to ensure clean state
    CALLABLE_REGISTRY.clear()

    # Import policies to register them via @policy_callable decorator
    from app.policies.store import (
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


class TestBuyerNegotiation:
    """Test buyer role negotiation (demanding compute, offering tokens)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("our_price,their_price,expected_action,reason", [
        # Buyer accepts up to 120% of max (within band)
        (100, 70, "accept_offer", "within buyer band"),
        (100, 80, "accept_offer", "within buyer band"),
        (100, 90, "accept_offer", "within buyer band"),
        (100, 100, "accept_offer", "equal to max"),
        (100, 110, "accept_offer", "within buyer band"),
        (100, 120, "accept_offer", "at buyer max (120%)"),

        # Buyer counters if reasonable but above 120%
        (100, 125, "counter_offer", "above band but reasonable"),
        (100, 130, "counter_offer", "above band but reasonable"),
        (100, 150, "counter_offer", "above band but reasonable"),
        (100, 180, "counter_offer", "above band but reasonable"),
        (100, 200, "counter_offer", "at reasonable upper bound"),

        # Buyer exits far outside reasonable
        (100, 40, "exit_negotiation", "far below 50%"),
        (100, 49, "exit_negotiation", "below reasonable"),
        (100, 250, "exit_negotiation", "far above 200%"),
    ])
    async def test_buyer_price_aware_decision(self, policy_store, our_price, their_price, expected_action, reason):
        """Test buyer negotiation policy at various price points."""
        event = NegotiationEvent.create(
            event_id=f"evt_test_buyer_{our_price}_{their_price}",
            negotiation_id=f"test_buyer_{our_price}_{their_price}",
            message_type="counter_proposal",
            sender="other_agent",
            data={
                "our_price": our_price,
                "their_price": their_price,
                "our_order_id": "order_our",
                "their_order_id": "order_their",
                "role": "buyer",
            }
        )

        context = DecisionContext(
            event=event,
            agent_id="test_agent",
            available_resources={},
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        assert func is not None, "Policy not registered"

        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        assert result is not None, f"Policy returned None for: our={our_price}, their={their_price}, reason={reason}"
        assert result.action_type.value == expected_action, \
            f"Expected {expected_action}, got {result.action_type.value} for: our={our_price}, their={their_price}, reason={reason}"

    @pytest.mark.asyncio
    async def test_buyer_counter_calculation(self, policy_store):
        """Test buyer counter-offer price calculation."""
        event = NegotiationEvent.create(
            event_id="evt_test_buyer_counter",
            negotiation_id="test_buyer_counter",
            message_type="counter_proposal",
            sender="other_agent",
            data={
                "our_price": 100,
                "their_price": 150,
                "our_order_id": "order_our",
                "their_order_id": "order_their",
                "role": "buyer",
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

        # Should counter with midpoint: (100 + 150) // 2 = 125
        assert result is not None
        assert result.action_type.value == "counter_offer"
        assert result.parameters.get("proposed_price") == 125


class TestSellerNegotiation:
    """Test seller role negotiation (offering compute, demanding tokens)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("our_price,their_price,expected_action,reason", [
        # Seller accepts at least 80% of min (within band)
        (100, 80, "accept_offer", "at seller min (80%)"),
        (100, 85, "accept_offer", "within seller band"),
        (100, 90, "accept_offer", "within seller band"),
        (100, 100, "accept_offer", "equal to min"),
        (100, 110, "accept_offer", "within seller band"),
        (100, 120, "accept_offer", "within seller band"),
        (100, 150, "accept_offer", "within seller band"),
        (100, 180, "accept_offer", "within seller band"),
        (100, 200, "accept_offer", "at seller upper bound"),

        # Seller counters if reasonable but below 80%
        (100, 75, "counter_offer", "below band but reasonable"),
        (100, 70, "counter_offer", "below band but reasonable"),
        (100, 60, "counter_offer", "below band but reasonable"),
        (100, 50, "counter_offer", "at reasonable lower bound"),

        # Seller exits far outside reasonable
        (100, 40, "exit_negotiation", "far below 50%"),
        (100, 49, "exit_negotiation", "below reasonable"),
        (100, 250, "exit_negotiation", "far above 200%"),
    ])
    async def test_seller_price_aware_decision(self, policy_store, our_price, their_price, expected_action, reason):
        """Test seller negotiation policy at various price points."""
        event = NegotiationEvent.create(
            event_id=f"evt_test_seller_{our_price}_{their_price}",
            negotiation_id=f"test_seller_{our_price}_{their_price}",
            message_type="counter_proposal",
            sender="other_agent",
            data={
                "our_price": our_price,
                "their_price": their_price,
                "our_order_id": "order_our",
                "their_order_id": "order_their",
                "role": "seller",
            }
        )

        context = DecisionContext(
            event=event,
            agent_id="test_agent",
            available_resources={},
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        assert func is not None, "Policy not registered"

        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        assert result is not None, f"Policy returned None for: our={our_price}, their={their_price}, reason={reason}"
        assert result.action_type.value == expected_action, \
            f"Expected {expected_action}, got {result.action_type.value} for: our={our_price}, their={their_price}, reason={reason}"

    @pytest.mark.asyncio
    async def test_seller_counter_calculation(self, policy_store):
        """Test seller counter-offer price calculation."""
        event = NegotiationEvent.create(
            event_id="evt_test_seller_counter",
            negotiation_id="test_seller_counter",
            message_type="counter_proposal",
            sender="other_agent",
            data={
                "our_price": 100,
                "their_price": 70,
                "our_order_id": "order_our",
                "their_order_id": "order_their",
                "role": "seller",
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

        # Should counter with midpoint: (100 + 70) // 2 = 85
        assert result is not None
        assert result.action_type.value == "counter_offer"
        assert result.parameters.get("proposed_price") == 85


class TestNegotiationScenarios:
    """Test realistic negotiation scenarios."""

    @pytest.mark.asyncio
    async def test_no_role_passes_to_next_policy(self, policy_store):
        """Test that policy passes to next policy when no role is specified."""
        event = NegotiationEvent.create(
            event_id="evt_test_no_role",
            negotiation_id="test_no_role",
            message_type="counter_proposal",
            sender="other_agent",
            data={
                "our_price": 100,
                "their_price": 110,
                "our_order_id": "order_our",
                "their_order_id": "order_their",
                # No role specified
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

        # Should return None (pass to next policy) when no role specified
        assert result is None, "Policy should pass to next policy when no role is specified"

    @pytest.mark.asyncio
    async def test_buyer_seller_equilibrium(self, policy_store):
        """Test that buyer and seller reach equilibrium at same price.

        Buyer at 100 (max) receives offer at 110 → accepts
        Seller at 100 (min) receives offer at 110 → accepts
        Equilibrium reached!
        """
        # Buyer perspective
        buyer_event = NegotiationEvent.create(
            event_id="evt_test_buyer_eq",
            negotiation_id="test_eq",
            message_type="counter_proposal",
            sender="seller_agent",
            data={"our_price": 100, "their_price": 110, "role": "buyer",
                   "our_order_id": "order_buyer", "their_order_id": "order_seller"}
        )

        buyer_context = DecisionContext(
            event=buyer_event,
            agent_id="buyer_agent",
            available_resources={},
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        buyer_result = await ce.evaluate(buyer_context)

        # Seller perspective
        seller_event = NegotiationEvent.create(
            event_id="evt_test_seller_eq",
            negotiation_id="test_eq",
            message_type="counter_proposal",
            sender="buyer_agent",
            data={"our_price": 100, "their_price": 110, "role": "seller",
                   "our_order_id": "order_seller", "their_order_id": "order_buyer"}
        )

        seller_context = DecisionContext(
            event=seller_event,
            agent_id="seller_agent",
            available_resources={},
            negotiation_history=[]
        )

        seller_result = await ce.evaluate(seller_context)

        # Both should accept at 110
        assert buyer_result.action_type.value == "accept_offer"
        assert seller_result.action_type.value == "accept_offer"

    @pytest.mark.asyncio
    async def test_buyer_seller_counter_convergence(self, policy_store):
        """Test that buyer and seller counter-offers converge toward equilibrium.

        Initial: Buyer at 100, Seller at 100
        Offer: 150 (too high for buyer, good for seller)
        Expected: Buyer counters to 125
        """
        # Buyer sees 150 → counters to 125
        buyer_event = NegotiationEvent.create(
            event_id="evt_test_buyer_conv",
            negotiation_id="test_conv",
            message_type="counter_proposal",
            sender="seller_agent",
            data={"our_price": 100, "their_price": 150, "role": "buyer",
                   "our_order_id": "order_buyer", "their_order_id": "order_seller"}
        )

        buyer_context = DecisionContext(
            event=buyer_event,
            agent_id="buyer_agent",
            available_resources={},
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)
        buyer_result = await ce.evaluate(buyer_context)

        # Buyer should counter
        assert buyer_result.action_type.value == "counter_offer"
        assert buyer_result.parameters.get("proposed_price") == 125

        # Seller sees 125 (from buyer counter) → should accept (>= 80% of min)
        seller_event = NegotiationEvent.create(
            event_id="evt_test_seller_conv",
            negotiation_id="test_conv",
            message_type="counter_proposal",
            sender="buyer_agent",
            data={"our_price": 100, "their_price": 125, "role": "seller",
                   "our_order_id": "order_seller", "their_order_id": "order_buyer"}
        )

        seller_context = DecisionContext(
            event=seller_event,
            agent_id="seller_agent",
            available_resources={},
            negotiation_history=[]
        )

        seller_result = await ce.evaluate(seller_context)

        # Seller should accept at 125
        assert seller_result.action_type.value == "accept_offer"

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
                "our_price": our_price,
                "their_price": their_price,
                "our_order_id": "order_our",
                "their_order_id": "order_their",
            }
        )

        context = DecisionContext(
            event=event,
            agent_id="test_agent",
            available_resources={},
            negotiation_history=[]
        )

        func = policy_store._registry.get("negotiation.action.safe_default_reject")
        ce = CallableEvaluator(func)
        result = await ce.evaluate(context)

        # Should reject for safety
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
            data={
                # Missing our_price and their_price
                "our_order_id": "order_our",
                "their_order_id": "order_their",
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
        from app.policies.negotiation_thread import NegotiationThreadStore
        sqlite_client = SQLiteClient(db_path=temp_db)
        return NegotiationThreadStore(sqlite_client=sqlite_client)

    @pytest.mark.asyncio
    async def test_buyer_negotiates_with_multiple_sellers(self, policy_store, thread_store):
        """Agent A (buyer) negotiates with Agents B and C (sellers) independently.

        Scenario:
        - Agent A is a buyer with order_A (max price 100)
        - Agent B is a seller with order_B (asking 150)
        - Agent C is a seller with order_C (asking 130)
        - A should counter both B and C independently
        """
        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)

        # Create negotiation threads for A↔B and A↔C
        await thread_store.create_thread(
            negotiation_id="order_A_order_B",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
        )
        await thread_store.create_thread(
            negotiation_id="order_A_order_C",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
        )

        # Agent A receives offer from Agent B (price 150)
        event_from_B = NegotiationEvent.create(
            event_id="evt_A_from_B",
            negotiation_id="order_A_order_B",
            message_type="initial_proposal",
            sender="agent_B",
            data={
                "our_price": 100,
                "their_price": 150,
                "our_order_id": "order_A",
                "their_order_id": "order_B",
                "role": "buyer",
            }
        )
        context_B = DecisionContext(
            event=event_from_B,
            agent_id="agent_A",
            available_resources={},
            negotiation_history=[]
        )

        # Agent A receives offer from Agent C (price 130)
        event_from_C = NegotiationEvent.create(
            event_id="evt_A_from_C",
            negotiation_id="order_A_order_C",
            message_type="initial_proposal",
            sender="agent_C",
            data={
                "our_price": 100,
                "their_price": 130,
                "our_order_id": "order_A",
                "their_order_id": "order_C",
                "role": "buyer",
            }
        )
        context_C = DecisionContext(
            event=event_from_C,
            agent_id="agent_A",
            available_resources={},
            negotiation_history=[]
        )

        # Evaluate both negotiations
        result_B = await ce.evaluate(context_B)
        result_C = await ce.evaluate(context_C)

        # Both should counter (150 and 130 are above 120% of 100)
        assert result_B.action_type.value == "counter_offer"
        assert result_C.action_type.value == "counter_offer"

        # Counter prices should be different (midpoints)
        assert result_B.parameters.get("proposed_price") == 125  # (100 + 150) // 2
        assert result_C.parameters.get("proposed_price") == 115  # (100 + 130) // 2

        # Record messages to threads
        await thread_store.add_message(
            negotiation_id="order_A_order_B",
            sender="agent_A",
            our_price=100,
            their_price=150,
            proposed_price=125,
            action_taken="COUNTER_OFFER",
            message_type="counter_proposal",
        )
        await thread_store.add_message(
            negotiation_id="order_A_order_C",
            sender="agent_A",
            our_price=100,
            their_price=130,
            proposed_price=115,
            action_taken="COUNTER_OFFER",
            message_type="counter_proposal",
        )

        # Verify threads are independent
        thread_B = await thread_store.get_thread("order_A_order_B")
        thread_C = await thread_store.get_thread("order_A_order_C")

        assert len(thread_B) == 1
        assert len(thread_C) == 1
        assert thread_B[0]["proposed_price"] == 125
        assert thread_C[0]["proposed_price"] == 115

    @pytest.mark.asyncio
    async def test_accept_cancels_competing_negotiations(self, policy_store, thread_store):
        """When A accepts B's offer, A's negotiation with C should be canceled.

        Scenario:
        - Agent A has active negotiations with B and C for order_A
        - B counters with price 110 (acceptable for buyer A)
        - A accepts B's offer
        - Negotiation A↔C should be canceled
        """
        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)

        # Create both negotiation threads
        await thread_store.create_thread(
            negotiation_id="order_A_order_B",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
        )
        await thread_store.create_thread(
            negotiation_id="order_A_order_C",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
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

        # Agent B counters with 110 (within buyer's band)
        event_accept = NegotiationEvent.create(
            event_id="evt_A_accept_B",
            negotiation_id="order_A_order_B",
            message_type="counter_proposal",
            sender="agent_B",
            data={
                "our_price": 100,
                "their_price": 110,
                "our_order_id": "order_A",
                "their_order_id": "order_B",
                "role": "buyer",
            }
        )
        context = DecisionContext(
            event=event_accept,
            agent_id="agent_A",
            available_resources={},
            negotiation_history=[]
        )

        result = await ce.evaluate(context)
        assert result.action_type.value == "accept_offer"

        # Simulate accept_offer action: cancel competing negotiations
        canceled = await thread_store._sqlite.cancel_negotiations_for_order(
            order_id="order_A",
            except_negotiation_id="order_A_order_B",
        )

        # Verify A↔C was canceled
        assert "order_A_order_C" in canceled

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
        )
        await thread_store.create_thread(
            negotiation_id="neg_2",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
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
    async def test_multi_round_convergence_with_multiple_sellers(self, policy_store, thread_store):
        """Test multi-round negotiation where buyer converges with one seller.

        Scenario:
        - Round 1: A counters B (150→125) and C (130→115)
        - Round 2: B counters 120, C counters 125
        - A accepts B's 120 (within band), cancels C
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
        )
        await thread_store.create_thread(
            negotiation_id="A_C",
            our_order_id="order_A",
            their_order_id="order_C",
            our_agent_id="agent_A",
            their_agent_id="agent_C",
        )

        # Round 1: Both sellers offer high prices
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

        # Round 2: B counters with 120 (acceptable), C counters with 125 (also needs counter)
        # First check B's counter of 120
        event_B_round2 = NegotiationEvent.create(
            event_id="evt_B_r2",
            negotiation_id="A_B",
            message_type="counter_proposal",
            sender="agent_B",
            data={
                "our_price": 100,
                "their_price": 120,
                "our_order_id": "order_A",
                "their_order_id": "order_B",
                "role": "buyer",
            }
        )

        # Use negotiation history to simulate prior round
        context_B_r2 = DecisionContext(
            event=event_B_round2,
            agent_id="agent_A",
            available_resources={},
            negotiation_history=[
                {"sender": "agent_A", "proposed_price": 125, "action_taken": "COUNTER_OFFER"}
            ]
        )

        result_B = await ce.evaluate(context_B_r2)
        # 120 is at boundary (120% of 100), should accept
        assert result_B.action_type.value == "accept_offer"

        # Check C's counter of 125 (above 120%, needs counter)
        event_C_round2 = NegotiationEvent.create(
            event_id="evt_C_r2",
            negotiation_id="A_C",
            message_type="counter_proposal",
            sender="agent_C",
            data={
                "our_price": 100,
                "their_price": 125,
                "our_order_id": "order_A",
                "their_order_id": "order_C",
                "role": "buyer",
            }
        )

        context_C_r2 = DecisionContext(
            event=event_C_round2,
            agent_id="agent_A",
            available_resources={},
            negotiation_history=[
                {"sender": "agent_A", "proposed_price": 115, "action_taken": "COUNTER_OFFER"}
            ]
        )

        result_C = await ce.evaluate(context_C_r2)
        # 125 is above 120%, should counter with midpoint of (115 + 125) // 2 = 120
        assert result_C.action_type.value == "counter_offer"
        assert result_C.parameters.get("proposed_price") == 120

        # Now A accepts B, which should cancel C
        canceled = await thread_store._sqlite.cancel_negotiations_for_order(
            order_id="order_A",
            except_negotiation_id="A_B",
        )

        assert "A_C" in canceled

    @pytest.mark.asyncio
    async def test_seller_negotiates_with_multiple_buyers(self, policy_store, thread_store):
        """Agent A (seller) negotiates with Agents B and C (buyers) independently.

        Scenario:
        - Agent A is a seller with order_A (min price 100)
        - Agent B is a buyer with order_B (offering 70)
        - Agent C is a buyer with order_C (offering 90)
        - A should counter B (below 80%) and accept C (at 90% >= 80%)
        """
        func = policy_store._registry.get("negotiation.action.price_interval_concession")
        ce = CallableEvaluator(func)

        # Agent A (seller) receives offer from Agent B (price 70)
        event_from_B = NegotiationEvent.create(
            event_id="evt_A_from_B_seller",
            negotiation_id="order_A_order_B",
            message_type="initial_proposal",
            sender="agent_B",
            data={
                "our_price": 100,
                "their_price": 70,
                "our_order_id": "order_A",
                "their_order_id": "order_B",
                "role": "seller",
            }
        )
        context_B = DecisionContext(
            event=event_from_B,
            agent_id="agent_A",
            available_resources={},
            negotiation_history=[]
        )

        # Agent A (seller) receives offer from Agent C (price 90)
        event_from_C = NegotiationEvent.create(
            event_id="evt_A_from_C_seller",
            negotiation_id="order_A_order_C",
            message_type="initial_proposal",
            sender="agent_C",
            data={
                "our_price": 100,
                "their_price": 90,
                "our_order_id": "order_A",
                "their_order_id": "order_C",
                "role": "seller",
            }
        )
        context_C = DecisionContext(
            event=event_from_C,
            agent_id="agent_A",
            available_resources={},
            negotiation_history=[]
        )

        result_B = await ce.evaluate(context_B)
        result_C = await ce.evaluate(context_C)

        # B's offer of 70 is below 80% (80), so seller should counter
        assert result_B.action_type.value == "counter_offer"
        assert result_B.parameters.get("proposed_price") == 85  # (100 + 70) // 2

        # C's offer of 90 is >= 80% (80), so seller should accept
        assert result_C.action_type.value == "accept_offer"
