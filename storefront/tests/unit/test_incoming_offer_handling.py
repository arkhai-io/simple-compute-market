"""Tests for incoming MAKE_OFFER event handling and thread creation.

Tests the negotiation.respond_to_make_offer policy and thread creation
with our_initial_price and our_strategy.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from market_storefront.schema.pydantic_models import (
    DecisionContext,
    MakeOfferEvent,
    MarketOrder,
    TokenResource,
    ComputeResource,
    EventType,
    ERC20TokenMetadata,
    GPUModel,
    Region,
)
from market_policy.store import PolicyStore
from domain.compute.agent.app.policy.store import negotiation_respond_to_make_offer
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.utils.action_executor import _extract_initial_price_from_order
from market_storefront.utils.validation import determine_strategy_from_order
import tempfile
import os


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def token_resource():
    return TokenResource(
        token=ERC20TokenMetadata(
            symbol="USDC",
            contract_address="0x1234",
            decimals=6,
        ),
        amount=100,
    )


@pytest.fixture
def compute_resource():
    return ComputeResource(
        gpu_model=GPUModel.H200,
        quantity=1,
        sla=99.9,
        region=Region.CALIFORNIA_US,
    )


@pytest.fixture
def minimizer_order(token_resource, compute_resource):
    """Minimizer order: demanding compute, offering tokens."""
    return MarketOrder(
        order_id="order_minimizer",
        order_maker="agent_minimizer",
        offer_resource=token_resource,
        demand_resource=compute_resource,
        duration_hours=3600,
    )


@pytest.fixture
def maximizer_order(token_resource, compute_resource):
    """Maximizer order: offering compute, demanding tokens."""
    return MarketOrder(
        order_id="order_maximizer",
        order_maker="agent_maximizer",
        offer_resource=compute_resource,
        demand_resource=token_resource,
        duration_hours=3600,
    )


class TestExtractInitialPrice:
    """Test _extract_initial_price_from_order helper function."""

    def test_extract_from_minimizer_order(self, minimizer_order):
        """Minimizer: token is in offer_resource (amount they will pay)."""
        price = _extract_initial_price_from_order(minimizer_order)
        assert price == 100

    def test_extract_from_maximizer_order(self, maximizer_order):
        """Maximizer: token is in demand_resource (amount they want to receive)."""
        price = _extract_initial_price_from_order(maximizer_order)
        assert price == 100

    def test_extract_from_dict(self, minimizer_order):
        """Test extraction from order dict."""
        order_dict = minimizer_order.model_dump(mode="json")
        price = _extract_initial_price_from_order(order_dict)
        assert price == 100

    def test_extract_no_token_raises_error(self):
        """Order with no token resource raises ValueError."""
        order = MarketOrder(
            order_id="order_compute_only",
            order_maker="agent_compute",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=99.9,
                region=Region.CALIFORNIA_US,
            ),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.TESLA_V100,
                quantity=1,
                sla=99.9,
                region=Region.NEW_YORK_US,
            ),
            duration_hours=3600,
        )

        with pytest.raises(ValueError, match="Order has no token resource"):
            _extract_initial_price_from_order(order)


class TestRespondToMakeOffer:
    """Test negotiation.respond_to_make_offer policy."""

    @pytest.fixture
    def thread_store(self, temp_db):
        from market_policy.negotiation_thread import NegotiationThreadStore
        from market_policy.identity import Identity
        return NegotiationThreadStore(
            sqlite_client=SQLiteClient(db_path=temp_db),
            identity=Identity(agent_url="http://localhost:8001"),
        )

    @pytest.fixture
    def policy_store(self, temp_db, thread_store):
        from unittest.mock import patch
        from market_policy.registry import CALLABLE_REGISTRY

        CALLABLE_REGISTRY.clear()

        from domain.compute.agent.app.policy.store import negotiation_respond_to_make_offer

        sqlite_client = SQLiteClient(db_path=temp_db)
        store = PolicyStore(sqlite_client=sqlite_client)
        store.register_callables({
            "negotiation.respond_to_make_offer": negotiation_respond_to_make_offer,
        })

        with patch("domain.compute.agent.app.policy.store.get_thread_store", return_value=thread_store):
            yield store
            CALLABLE_REGISTRY.clear()

    @pytest.mark.asyncio
    async def test_minimizer_accepts_favorable_price(self, policy_store, maximizer_order):
        """Minimizer accepts when their_price <= our_price * (1 + CONVERGENCE_RATIO)."""
        minimizer_our_order = MarketOrder(
            order_id="our_order",
            order_maker="our_agent",
            offer_resource=TokenResource(
                token=ERC20TokenMetadata(
                    symbol="USDC",
                    contract_address="0x1234",
                    decimals=6,
                ),
                amount=100,
            ),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=99.9,
                region=Region.CALIFORNIA_US,
            ),
            duration_hours=3600,
        )

        event = MakeOfferEvent(
            event_id="evt_incoming",
            source="agent_maximizer",
            order=maximizer_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[
                minimizer_our_order.model_dump(mode="json"),
            ])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        assert result is not None
        assert result.action_type.value == "accept_offer"
        assert result.parameters.get("reason") == "convergence"

    @pytest.mark.asyncio
    async def test_minimizer_counters_reasonable_price(self, policy_store):
        """Minimizer counters when our_price < their_price <= 1.5x our_price."""
        # Our minimizer order: we offer 100 tokens
        minimizer_our_order = MarketOrder(
            order_id="our_order",
            order_maker="our_agent",
            offer_resource=TokenResource(
                token=ERC20TokenMetadata(
                    symbol="USDC",
                    contract_address="0x1234",
                    decimals=6,
                ),
                amount=100,
            ),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=99.9,
                region=Region.CALIFORNIA_US,
            ),
            duration_hours=3600,
        )

        # Incoming maximizer order: they demand 120 tokens (higher than our 100)
        incoming_maximizer_order = MarketOrder(
            order_id="order_maximizer",
            order_maker="agent_maximizer",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=99.9,
                region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(
                token=ERC20TokenMetadata(
                    symbol="USDC",
                    contract_address="0x1234",
                    decimals=6,
                ),
                amount=120,  # Higher than our 100, but within 1.5x
            ),
            duration_hours=3600,
        )

        event = MakeOfferEvent(
            event_id="evt_incoming",
            source="agent_maximizer",
            order=incoming_maximizer_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[
                minimizer_our_order.model_dump(mode="json"),
            ])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        assert result is not None
        assert result.action_type.value == "counter_offer"
        # proposed_price = (100 + 120) // 2 = 110  (midpoint, no clamp)
        assert result.parameters.get("proposed_price") == 110

    @pytest.mark.asyncio
    async def test_minimizer_exits_unreasonable_price(self, policy_store):
        """Minimizer exits when their_price > 1.5x our_price."""
        expensive_order = MarketOrder(
            order_id="expensive_order",
            order_maker="agent_expensive",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=99.9,
                region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(
                token=ERC20TokenMetadata(
                    symbol="USDC",
                    contract_address="0x1234",
                    decimals=6,
                ),
                amount=200,
            ),
            duration_hours=3600,
        )

        minimizer_our_order = MarketOrder(
            order_id="our_order",
            order_maker="our_agent",
            offer_resource=TokenResource(
                token=ERC20TokenMetadata(
                    symbol="USDC",
                    contract_address="0x1234",
                    decimals=6,
                ),
                amount=100,
            ),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=99.9,
                region=Region.CALIFORNIA_US,
            ),
            duration_hours=3600,
        )

        event = MakeOfferEvent(
            event_id="evt_incoming",
            source="agent_expensive",
            order=expensive_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[
                minimizer_our_order.model_dump(mode="json"),
            ])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        assert result is not None
        assert result.action_type.value == "exit_negotiation"

    @pytest.mark.asyncio
    async def test_maximizer_accepts_favorable_price(self, policy_store, minimizer_order):
        """Maximizer accepts when their_price >= our_price."""
        maximizer_our_order = MarketOrder(
            order_id="our_order",
            order_maker="our_agent",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200,
                quantity=1,
                sla=99.9,
                region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(
                token=ERC20TokenMetadata(
                    symbol="USDC",
                    contract_address="0x1234",
                    decimals=6,
                ),
                amount=100,
            ),
            duration_hours=3600,
        )

        event = MakeOfferEvent(
            event_id="evt_incoming",
            source="agent_minimizer",
            order=minimizer_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[
                maximizer_our_order.model_dump(mode="json"),
            ])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        assert result is not None
        assert result.action_type.value == "accept_offer"

    @pytest.mark.asyncio
    async def test_maximizer_counters_reasonable_price(self, policy_store):
        """Maximizer counters when 0.67x our_price <= their_price < our_price."""
        cheap_order = MarketOrder(
            order_id="cheap_order",
            order_maker="agent_cheap",
            offer_resource=TokenResource(
                token=ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6),
                amount=70,
            ),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            duration_hours=3600,
        )

        maximizer_our_order = MarketOrder(
            order_id="our_order",
            order_maker="our_agent",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(
                token=ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6),
                amount=100,
            ),
            duration_hours=3600,
        )

        event = MakeOfferEvent(
            event_id="evt_incoming",
            source="agent_cheap",
            order=cheap_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[
                maximizer_our_order.model_dump(mode="json"),
            ])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        assert result is not None
        assert result.action_type.value == "counter_offer"
        # proposed_price = (100 + 70) // 2 = 85  (midpoint, no clamp)
        assert result.parameters.get("proposed_price") == 85

    @pytest.mark.asyncio
    async def test_no_matching_order_returns_reject(self, policy_store, maximizer_order):
        """Policy rejects when no matching order found."""
        event = MakeOfferEvent(
            event_id="evt_incoming",
            source="agent_maximizer",
            order=maximizer_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        assert result is not None
        assert result.action_type.value == "reject_offer"
        assert result.parameters.get("reason") == "no_matching_order"

    @pytest.mark.asyncio
    async def test_non_make_offer_event_returns_none(self, policy_store):
        """Policy returns None for non-make_offer events."""
        from market_storefront.schema.pydantic_models import NegotiationEvent

        event = NegotiationEvent.create(
            event_id="evt_negotiation",
            negotiation_id="test_neg",
            message_type="counter_proposal",
            sender="other_agent",
            data={"proposed_price": 100},
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        func = policy_store._registry.get("negotiation.respond_to_make_offer")
        result = await func(context)

        assert result is None

    @pytest.mark.asyncio
    async def test_negotiation_id_deterministic(self, policy_store, maximizer_order):
        """Negotiation ID is canonical (sorted) when we are the responder (order sorts second)."""
        # our order_id "order_Z" > their "order_A" → we are the responder, guard does not fire
        minimizer_our_order = MarketOrder(
            order_id="order_Z",
            order_maker="our_agent",
            offer_resource=TokenResource(
                token=ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6),
                amount=100,
            ),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            duration_hours=3600,
        )

        incoming_order = MarketOrder(
            order_id="order_A",
            order_maker="agent_B",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(
                token=ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6),
                amount=100,
            ),
            duration_hours=3600,
        )

        event = MakeOfferEvent(
            event_id="evt_incoming",
            source="agent_B",
            order=incoming_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[
                minimizer_our_order.model_dump(mode="json"),
            ])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        assert result is not None
        neg_id = result.parameters.get("negotiation_id")
        assert neg_id == "order_A_order_Z"

    @pytest.mark.asyncio
    async def test_canonical_initiator_guard_drops_cross_offer(self, policy_store, thread_store):
        """When our order_id sorts first and a thread already exists, we are the initiator — incoming make_offer is dropped."""
        # our order_id "order_A" < their "order_Z" → we are the canonical initiator
        our_order_id = "order_A"
        their_order_id = "order_Z"
        neg_id = f"{our_order_id}_{their_order_id}"

        minimizer_our_order = MarketOrder(
            order_id=our_order_id,
            order_maker="our_agent",
            offer_resource=TokenResource(
                token=ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6),
                amount=100,
            ),
            demand_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            duration_hours=3600,
        )

        incoming_order = MarketOrder(
            order_id=their_order_id,
            order_maker="agent_Z",
            offer_resource=ComputeResource(
                gpu_model=GPUModel.H200, quantity=1, sla=99.9, region=Region.CALIFORNIA_US,
            ),
            demand_resource=TokenResource(
                token=ERC20TokenMetadata(symbol="USDC", contract_address="0x1234", decimals=6),
                amount=100,
            ),
            duration_hours=3600,
        )

        # Seed an existing thread: guard only fires when we already have an active thread,
        # proving we already sent our own make_offer outbound.
        await thread_store.create_thread(
            negotiation_id=neg_id,
            our_order_id=our_order_id,
            their_order_id=their_order_id,
            our_agent_id="our_agent",
            their_agent_id="agent_Z",
            owner_id="",   # matches CONFIG.base_url_override default in tests
            our_initial_price=100,
            our_strategy="minimize",
        )

        event = MakeOfferEvent(
            event_id="evt_cross",
            source="agent_Z",
            order=incoming_order,
        )

        context = DecisionContext(
            event=event,
            agent_id="our_agent",
            available_resources={},
            market_state={},
        )

        with patch("domain.compute.agent.app.policy.store.get_registry_client") as mock_get_registry:
            mock_registry = AsyncMock()
            mock_registry.query_orders = AsyncMock(return_value=[
                minimizer_our_order.model_dump(mode="json"),
            ])
            mock_get_registry.return_value = mock_registry

            func = policy_store._registry.get("negotiation.respond_to_make_offer")
            result = await func(context)

        # Canonical initiator guard: active thread exists, drop counterparty's cross-offer
        assert result is None


class TestThreadCreationWithInitialPriceAndStrategy:
    """Test thread creation includes our_initial_price and our_strategy."""

    @pytest.fixture
    def thread_store(self, temp_db):
        from market_policy.negotiation_thread import NegotiationThreadStore
        from market_policy.identity import Identity
        sqlite_client = SQLiteClient(db_path=temp_db)
        return NegotiationThreadStore(
            sqlite_client=sqlite_client,
            identity=Identity(agent_url="http://localhost:8001"),
        )

    @pytest.mark.asyncio
    async def test_thread_created_with_initial_price_and_strategy(self, thread_store):
        """Thread stores our_initial_price and our_strategy locally."""
        await thread_store.create_thread(
            negotiation_id="test_neg_1",
            our_order_id="order_our",
            their_order_id="order_their",
            our_agent_id="agent_our",
            their_agent_id="agent_their",
            owner_id="agent_our",
            our_initial_price=100,
            our_strategy="minimize",
        )

        thread_info = await thread_store.get_thread_info(
            negotiation_id="test_neg_1",
            owner_id="agent_our",
        )

        assert thread_info is not None
        assert thread_info["our_initial_price"] == 100
        assert thread_info["our_strategy"] == "minimize"

    @pytest.mark.asyncio
    async def test_local_state_isolated_per_agent(self, thread_store):
        """Each agent has their own local_state for the same negotiation."""
        await thread_store.create_thread(
            negotiation_id="test_neg_2",
            our_order_id="order_A",
            their_order_id="order_B",
            our_agent_id="agent_A",
            their_agent_id="agent_B",
            owner_id="agent_A",
            our_initial_price=100,
            our_strategy="minimize",
        )

        await thread_store.create_thread(
            negotiation_id="test_neg_2",
            our_order_id="order_B",
            their_order_id="order_A",
            our_agent_id="agent_B",
            their_agent_id="agent_A",
            owner_id="agent_B",
            our_initial_price=100,
            our_strategy="maximize",
        )

        state_A = await thread_store.get_thread_info(
            negotiation_id="test_neg_2",
            owner_id="agent_A",
        )
        state_B = await thread_store.get_thread_info(
            negotiation_id="test_neg_2",
            owner_id="agent_B",
        )

        assert state_A["our_strategy"] == "minimize"
        assert state_B["our_strategy"] == "maximize"

    @pytest.mark.asyncio
    async def test_public_thread_does_not_expose_strategy(self, thread_store):
        """Public thread info does not expose private strategy."""
        await thread_store.create_thread(
            negotiation_id="test_neg_3",
            our_order_id="order_our",
            their_order_id="order_their",
            our_agent_id="agent_our",
            their_agent_id="agent_their",
            owner_id="agent_our",
            our_initial_price=100,
            our_strategy="minimize",
        )

        thread_info = await thread_store.get_thread_info(
            negotiation_id="test_neg_3",
            owner_id="agent_their",  # Different owner won't see private state
        )

        assert thread_info is not None
        # Different owner can't see private state (values are None)
        assert thread_info.get("our_strategy") is None
        assert thread_info.get("our_initial_price") is None
