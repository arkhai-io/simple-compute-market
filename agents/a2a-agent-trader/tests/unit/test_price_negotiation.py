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
