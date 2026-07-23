"""Tests for the settlement aggregate's table-driven transition validator."""

from __future__ import annotations

import pytest

from market_fulfillment.transitions import InvalidSettlementTransitionError, validate_transition


def test_legal_forward_edges_are_accepted():
    validate_transition("assigned", "dispatch_pending")
    validate_transition("dispatch_pending", "dispatching")
    validate_transition("dispatching", "active")
    validate_transition("active", "teardown_dispatch_pending")
    validate_transition("teardown_dispatch_pending", "tearing_down")
    validate_transition("tearing_down", "torn_down")


def test_assigned_may_be_abandoned_without_ever_dispatching():
    validate_transition("assigned", "abandoned")


def test_teardown_failed_may_retry_teardown_dispatch():
    validate_transition("teardown_failed", "teardown_dispatch_pending")


def test_terminal_states_have_no_outgoing_edges():
    for terminal in ("failed", "torn_down", "abandoned"):
        with pytest.raises(InvalidSettlementTransitionError):
            validate_transition(terminal, "dispatch_pending")


def test_illegal_skip_is_rejected():
    with pytest.raises(InvalidSettlementTransitionError):
        validate_transition("assigned", "active")


def test_backward_transition_is_rejected():
    with pytest.raises(InvalidSettlementTransitionError):
        validate_transition("active", "dispatch_pending")


def test_unknown_state_is_rejected():
    with pytest.raises(InvalidSettlementTransitionError):
        validate_transition("assigned", "not_a_real_state")
    with pytest.raises(InvalidSettlementTransitionError):
        validate_transition("not_a_real_state", "assigned")
