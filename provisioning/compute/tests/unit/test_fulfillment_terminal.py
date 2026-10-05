"""The registry of domain effects owed when a fulfillment record becomes terminal."""

from __future__ import annotations

import pytest
from compute_provisioning import (
    FULFILLMENT_TERMINAL_STATES,
    FulfillmentTerminalHooks,
)


def _recorder(calls, name):
    def hook(db, capacity_reservation_id, state):
        calls.append((name, db, capacity_reservation_id, state))

    return hook


def test_terminal_states_exclude_a_teardown_recovery_may_retry():
    assert FULFILLMENT_TERMINAL_STATES == {"failed", "torn_down", "abandoned"}


@pytest.mark.parametrize("state", sorted(FULFILLMENT_TERMINAL_STATES))
def test_every_hook_runs_in_order_with_the_callers_session(state):
    calls: list = []
    hooks = FulfillmentTerminalHooks()
    hooks.register(_recorder(calls, "first"))
    hooks.register(_recorder(calls, "second"))
    hooks.freeze()
    session = object()

    hooks.run(session, "cr-1", state)

    assert calls == [
        ("first", session, "cr-1", state),
        ("second", session, "cr-1", state),
    ]


@pytest.mark.parametrize("state", ["dispatching", "active", "teardown_failed"])
def test_a_state_that_is_not_terminal_runs_nothing(state):
    calls: list = []
    hooks = FulfillmentTerminalHooks()
    hooks.register(_recorder(calls, "only"))
    hooks.freeze()

    hooks.run(object(), "cr-1", state)

    assert calls == []


def test_nothing_runs_before_composition_freezes_the_registry():
    hooks = FulfillmentTerminalHooks()

    with pytest.raises(RuntimeError, match="not been composed"):
        hooks.run(object(), "cr-1", "failed")


def test_nothing_registers_once_frozen():
    hooks = FulfillmentTerminalHooks()
    hooks.freeze()

    with pytest.raises(RuntimeError, match="frozen"):
        hooks.register(lambda db, rid, state: None)


def test_a_hook_that_is_not_callable_is_refused():
    with pytest.raises(ValueError, match="not callable"):
        FulfillmentTerminalHooks().register("release ports")


def test_a_failing_hook_stops_the_run_so_its_transaction_aborts():
    calls: list = []

    def failing(db, capacity_reservation_id, state):
        raise RuntimeError("effect failed")

    hooks = FulfillmentTerminalHooks()
    hooks.register(failing)
    hooks.register(_recorder(calls, "after"))
    hooks.freeze()

    with pytest.raises(RuntimeError, match="effect failed"):
        hooks.run(object(), "cr-1", "torn_down")
    assert calls == []
