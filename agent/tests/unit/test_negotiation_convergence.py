"""Tests for negotiation convergence with round-dependent threshold relaxation.

Validates that:
- _relaxed_acceptance_threshold correctly computes round-dependent thresholds
- Multi-round negotiations converge to ACCEPT within MAX_NEGOTIATION_ROUNDS
- Out-of-ZOPA negotiations EXIT immediately (unchanged)
- Equal-price negotiations ACCEPT immediately (unchanged)
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.policies.store import (
    _relaxed_acceptance_threshold,
    negotiation_action_price_interval_concession,
    REASONABLE_MULTIPLIER,
    MAX_NEGOTIATION_ROUNDS,
)
from app.schema.pydantic_models import (
    DecisionContext,
    NegotiationEvent,
    EventType,
)


class TestRelaxedAcceptanceThreshold:
    """Test the _relaxed_acceptance_threshold helper function."""

    def test_round_0_equals_initial_price_minimize(self):
        """Minimizer: Round 0 threshold equals our_price (no relaxation)."""
        threshold = _relaxed_acceptance_threshold(100, "minimize", 0, MAX_NEGOTIATION_ROUNDS)
        assert threshold == 100

    def test_round_0_equals_initial_price_maximize(self):
        """Maximizer: Round 0 threshold equals our_price (no relaxation)."""
        threshold = _relaxed_acceptance_threshold(100, "maximize", 0, MAX_NEGOTIATION_ROUNDS)
        assert threshold == 100

    def test_final_round_equals_max_concession_minimize(self):
        """Minimizer: Final round threshold equals ceiling x 1.5."""
        final_round = MAX_NEGOTIATION_ROUNDS - 1
        threshold = _relaxed_acceptance_threshold(100, "minimize", final_round, MAX_NEGOTIATION_ROUNDS)
        expected = int(100 * REASONABLE_MULTIPLIER)  # 150
        assert threshold == expected

    def test_final_round_equals_max_concession_maximize(self):
        """Maximizer: Final round threshold equals floor / 1.5."""
        final_round = MAX_NEGOTIATION_ROUNDS - 1
        threshold = _relaxed_acceptance_threshold(100, "maximize", final_round, MAX_NEGOTIATION_ROUNDS)
        expected = int(100 / REASONABLE_MULTIPLIER)  # 66
        assert threshold == expected

    def test_intermediate_round_minimize(self):
        """Minimizer: Intermediate rounds produce intermediate thresholds."""
        # With our_price=100, max_concession=150, max_rounds=5
        # Round 2: fraction = 2/4 = 0.5, threshold = 100 + int(50*0.5) = 125
        threshold = _relaxed_acceptance_threshold(100, "minimize", 2, MAX_NEGOTIATION_ROUNDS)
        assert threshold == 125

    def test_intermediate_round_maximize(self):
        """Maximizer: Intermediate rounds produce intermediate thresholds."""
        # With our_price=100, max_concession=66, max_rounds=5
        # Round 2: fraction = 2/4 = 0.5, threshold = 100 - int(34*0.5) = 83
        threshold = _relaxed_acceptance_threshold(100, "maximize", 2, MAX_NEGOTIATION_ROUNDS)
        assert threshold == 83

    def test_monotonic_relaxation_minimize(self):
        """Minimizer threshold monotonically increases over rounds."""
        thresholds = [
            _relaxed_acceptance_threshold(100, "minimize", r, MAX_NEGOTIATION_ROUNDS)
            for r in range(MAX_NEGOTIATION_ROUNDS)
        ]
        for i in range(1, len(thresholds)):
            assert thresholds[i] >= thresholds[i - 1]

    def test_monotonic_relaxation_maximize(self):
        """Maximizer threshold monotonically decreases over rounds."""
        thresholds = [
            _relaxed_acceptance_threshold(100, "maximize", r, MAX_NEGOTIATION_ROUNDS)
            for r in range(MAX_NEGOTIATION_ROUNDS)
        ]
        for i in range(1, len(thresholds)):
            assert thresholds[i] <= thresholds[i - 1]

    def test_beyond_max_rounds_clamps(self):
        """Rounds beyond max_rounds clamp to max concession."""
        threshold_at_max = _relaxed_acceptance_threshold(100, "minimize", MAX_NEGOTIATION_ROUNDS, MAX_NEGOTIATION_ROUNDS)
        threshold_beyond = _relaxed_acceptance_threshold(100, "minimize", MAX_NEGOTIATION_ROUNDS + 5, MAX_NEGOTIATION_ROUNDS)
        assert threshold_at_max == threshold_beyond

    def test_seller_9_buyer_6_thresholds(self):
        """Verify thresholds for the convergence proof example (seller=9, buyer=6)."""
        # Seller (maximize, floor=9): relaxes downward toward 6
        seller_thresholds = [
            _relaxed_acceptance_threshold(9, "maximize", r, MAX_NEGOTIATION_ROUNDS)
            for r in range(MAX_NEGOTIATION_ROUNDS)
        ]
        assert seller_thresholds[0] == 9
        assert seller_thresholds[4] == 6  # int(9/1.5) = 6

        # Buyer (minimize, ceiling=6): relaxes upward toward 9
        buyer_thresholds = [
            _relaxed_acceptance_threshold(6, "minimize", r, MAX_NEGOTIATION_ROUNDS)
            for r in range(MAX_NEGOTIATION_ROUNDS)
        ]
        assert buyer_thresholds[0] == 6
        assert buyer_thresholds[4] == 9  # int(6*1.5) = 9


class TestNegotiationConvergence:
    """Simulate full multi-round negotiations and verify convergence."""

    def _make_negotiation_context(self, our_price, their_price, strategy, agent_id, negotiation_history):
        """Helper to build a DecisionContext for negotiation_action_price_interval_concession."""
        event = NegotiationEvent.create(
            event_id=f"evt_{len(negotiation_history)}",
            negotiation_id="test_neg",
            message_type="counter_proposal",
            sender="counterparty",
            data={"proposed_price": their_price},
        )
        return DecisionContext(
            event=event,
            agent_id=agent_id,
            available_resources={},
            market_state={
                "thread_info": {
                    "our_initial_price": our_price,
                    "our_strategy": strategy,
                    "our_order_id": f"order_{agent_id}",
                    "their_order_id": "order_counterparty",
                },
            },
            negotiation_history=negotiation_history,
        )

    def _simulate_negotiation(self, seller_price, buyer_price, max_rounds=MAX_NEGOTIATION_ROUNDS):
        """Simulate a bilateral negotiation between seller and buyer.

        Returns list of (round, sender, action_type, price) tuples.
        """
        history = []
        trace = []

        # Initial offer from seller: their price IS the seller_price
        current_offer = seller_price
        current_sender = "seller"

        for round_num in range(max_rounds * 2):  # Upper bound on total messages
            if current_sender == "seller":
                # Buyer responds
                ctx = self._make_negotiation_context(
                    our_price=buyer_price,
                    their_price=current_offer,
                    strategy="minimize",
                    agent_id="buyer",
                    negotiation_history=list(history),
                )
                result = negotiation_action_price_interval_concession(ctx)
                if result is None:
                    break

                action = result.action_type.value
                trace.append((len(history), "buyer", action, result.parameters.get("proposed_price", current_offer)))

                if action == "accept_offer":
                    return trace
                elif action == "exit_negotiation":
                    return trace
                elif action == "counter_offer":
                    history.append({"sender": "buyer", "proposed_price": result.parameters["proposed_price"]})
                    current_offer = result.parameters["proposed_price"]
                    current_sender = "buyer"
                else:
                    break
            else:
                # Seller responds
                ctx = self._make_negotiation_context(
                    our_price=seller_price,
                    their_price=current_offer,
                    strategy="maximize",
                    agent_id="seller",
                    negotiation_history=list(history),
                )
                result = negotiation_action_price_interval_concession(ctx)
                if result is None:
                    break

                action = result.action_type.value
                trace.append((len(history), "seller", action, result.parameters.get("proposed_price", current_offer)))

                if action == "accept_offer":
                    return trace
                elif action == "exit_negotiation":
                    return trace
                elif action == "counter_offer":
                    history.append({"sender": "seller", "proposed_price": result.parameters["proposed_price"]})
                    current_offer = result.parameters["proposed_price"]
                    current_sender = "seller"
                else:
                    break

        return trace

    def test_seller_9_buyer_6_converges(self):
        """Seller=9, buyer=6: Should ACCEPT within MAX_NEGOTIATION_ROUNDS."""
        trace = self._simulate_negotiation(seller_price=9, buyer_price=6)

        # Must end with acceptance
        assert len(trace) > 0, "Negotiation produced no actions"
        final_action = trace[-1][2]
        assert final_action == "accept_offer", f"Expected accept_offer, got {final_action}. Trace: {trace}"

        # Must converge within bounds
        final_round = trace[-1][0]
        assert final_round < MAX_NEGOTIATION_ROUNDS, f"Convergence took too many rounds: {final_round}"

    def test_seller_9_buyer_8_converges_quickly(self):
        """Seller=9, buyer=8: Close prices should converge within 2 rounds."""
        trace = self._simulate_negotiation(seller_price=9, buyer_price=8)

        assert len(trace) > 0
        final_action = trace[-1][2]
        assert final_action == "accept_offer", f"Expected accept_offer, got {final_action}. Trace: {trace}"

        # Close prices should converge fast
        final_round = trace[-1][0]
        assert final_round <= 3, f"Close prices should converge quickly, took {final_round} rounds"

    def test_equal_prices_immediate_accept(self):
        """Equal prices: Buyer accepts immediately at round 0."""
        trace = self._simulate_negotiation(seller_price=100, buyer_price=100)

        assert len(trace) > 0
        assert trace[0][2] == "accept_offer"
        assert trace[0][0] == 0  # Round 0

    def test_out_of_zopa_exits_immediately(self):
        """Out-of-ZOPA (ceiling*1.5 < floor/1.5): Buyer exits immediately."""
        # buyer_ceiling=3, seller_floor=9
        # buyer max concession = 3*1.5 = 4.5
        # seller min concession = 9/1.5 = 6
        # 4.5 < 6: no overlap, but buyer checks 9 <= 3*1.5=4.5 → False → exit
        trace = self._simulate_negotiation(seller_price=9, buyer_price=3)

        assert len(trace) > 0
        assert trace[0][2] == "exit_negotiation", f"Expected exit, got {trace[0][2]}. Trace: {trace}"

    def test_seller_100_buyer_80_converges(self):
        """Seller=100, buyer=80: Moderate gap should converge."""
        trace = self._simulate_negotiation(seller_price=100, buyer_price=80)

        assert len(trace) > 0
        final_action = trace[-1][2]
        assert final_action == "accept_offer", f"Expected accept_offer, got {final_action}. Trace: {trace}"

    def test_seller_100_buyer_70_converges(self):
        """Seller=100, buyer=70: Larger gap should still converge within ZOPA."""
        trace = self._simulate_negotiation(seller_price=100, buyer_price=70)

        assert len(trace) > 0
        final_action = trace[-1][2]
        assert final_action == "accept_offer", f"Expected accept_offer, got {final_action}. Trace: {trace}"
