"""The registry of what a deployment returns when a reservation's capacity is."""

from __future__ import annotations

import pytest
from compute_provisioning import ReleaseEffects


def _recorder(calls, name):
    def effect(db, capacity_reservation_id, state):
        calls.append((name, db, capacity_reservation_id, state))

    return effect


@pytest.mark.parametrize("state", ["released", "force_released"])
def test_every_effect_runs_in_order_with_the_ledgers_session(state):
    calls: list = []
    effects = ReleaseEffects()
    effects.register(_recorder(calls, "first"))
    effects.register(_recorder(calls, "second"))
    effects.freeze()
    session = object()

    effects(session, "cr-1", state)

    assert calls == [
        ("first", session, "cr-1", state),
        ("second", session, "cr-1", state),
    ]


def test_nothing_runs_before_composition_freezes_the_registry():
    with pytest.raises(RuntimeError, match="not been composed"):
        ReleaseEffects()(object(), "cr-1", "released")


def test_nothing_registers_once_frozen():
    effects = ReleaseEffects()
    effects.freeze()

    with pytest.raises(RuntimeError, match="frozen"):
        effects.register(lambda db, rid, state: None)


def test_an_effect_that_is_not_callable_is_refused():
    with pytest.raises(ValueError, match="not callable"):
        ReleaseEffects().register("release ports")


def test_a_failing_effect_stops_the_run_so_the_release_aborts():
    calls: list = []

    def failing(db, capacity_reservation_id, state):
        raise RuntimeError("effect failed")

    effects = ReleaseEffects()
    effects.register(failing)
    effects.register(_recorder(calls, "after"))
    effects.freeze()

    with pytest.raises(RuntimeError, match="effect failed"):
        effects(object(), "cr-1", "released")
    assert calls == []
