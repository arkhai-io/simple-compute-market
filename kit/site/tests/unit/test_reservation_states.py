"""The reservation states are the ones the lifecycle writes, and only its
transitions write them."""

from __future__ import annotations

import inspect

from market_site.authority import SiteAuthorityLedger
from market_site.db import HELD_RESERVATION_STATES, ReservationState
from market_site.ledger import CapacityLedgerService


def test_the_ledger_defines_only_the_states_its_lifecycle_writes() -> None:
    assert {state.value for state in ReservationState} == {
        "reserved",
        "leased",
        "releasing",
        "released",
        "release_failed",
        "unmanaged",
        "force_released",
    }
    assert set(HELD_RESERVATION_STATES) == {
        "reserved",
        "leased",
        "releasing",
        "release_failed",
        "unmanaged",
    }


def test_no_operation_takes_a_state_to_write() -> None:
    """A state is reached through a transition, each of which names the state
    it writes; no ledger or authority-protocol operation takes one from its
    caller, only the reservation list, which filters by one."""
    for owner in (CapacityLedgerService, SiteAuthorityLedger):
        for name, member in inspect.getmembers(owner, inspect.isfunction):
            if name.startswith("_") or name == "list_reservations":
                continue
            parameters = inspect.signature(member).parameters.values()
            assert not any(
                "state" in parameter.name
                or parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            ), name
