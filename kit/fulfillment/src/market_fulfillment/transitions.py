"""Table-driven state transition validation for the settlement aggregate.

A compact allowed-transitions table, not stored procedures or a bespoke
method per edge, is the mechanism: adding a state or a legal edge is a table
entry, and every transition is checked against the same table regardless of
which caller (scheduler, fulfillment acceptance, provider recovery, teardown,
or abandonment) is driving it.
"""

from __future__ import annotations

from .db import SettlementRecordState


class InvalidSettlementTransitionError(Exception):
    """Raised when a requested state change is not a legal edge in the table."""


#: The failure reason a compensating teardown records when it moves a
#: ``failed`` aggregate into teardown. Only that operation writes it, so a
#: ``torn_down`` aggregate carrying it ended compensated, while one carrying
#: any other reason was delivered: a delivered fulfillment whose teardown
#: failed once keeps that failure's reason after a later success.
CREATE_COMPENSATION = "create_compensation"


_ALLOWED_TRANSITIONS: dict[SettlementRecordState, frozenset[SettlementRecordState]] = {
    SettlementRecordState.assigned: frozenset(
        {SettlementRecordState.dispatch_pending, SettlementRecordState.abandoned}
    ),
    SettlementRecordState.dispatch_pending: frozenset(
        {SettlementRecordState.dispatching, SettlementRecordState.failed}
    ),
    SettlementRecordState.dispatching: frozenset(
        {SettlementRecordState.active, SettlementRecordState.failed}
    ),
    SettlementRecordState.active: frozenset({SettlementRecordState.teardown_dispatch_pending}),
    SettlementRecordState.teardown_dispatch_pending: frozenset(
        {SettlementRecordState.tearing_down, SettlementRecordState.teardown_failed}
    ),
    SettlementRecordState.tearing_down: frozenset(
        {SettlementRecordState.torn_down, SettlementRecordState.teardown_failed}
    ),
    # Not terminal: the periodic recovery sweep retries teardown dispatch.
    SettlementRecordState.teardown_failed: frozenset(
        {SettlementRecordState.teardown_dispatch_pending}
    ),
    # Taken only by a compensating teardown, which undoes what a failed create
    # may have left behind; ordinary teardown still begins only from active.
    SettlementRecordState.failed: frozenset(
        {SettlementRecordState.teardown_dispatch_pending}
    ),
    SettlementRecordState.torn_down: frozenset(),
    SettlementRecordState.abandoned: frozenset(),
}


def validate_transition(current: str, target: str) -> None:
    """Raise unless ``current -> target`` is a legal edge in the table.

    Callers that want retry-of-the-same-state to be a no-op (an equivalent
    retry that hasn't advanced the aggregate yet) should compare ``current
    == target`` themselves before calling this -- self-transitions are
    deliberately absent from the table so it only describes real state
    changes, not idempotent-retry bookkeeping.
    """

    try:
        current_state = SettlementRecordState(current)
        target_state = SettlementRecordState(target)
    except ValueError as exc:
        raise InvalidSettlementTransitionError(
            f"unknown settlement state in transition {current!r} -> {target!r}"
        ) from exc
    if target_state not in _ALLOWED_TRANSITIONS.get(current_state, frozenset()):
        raise InvalidSettlementTransitionError(
            f"cannot transition settlement record from {current!r} to {target!r}"
        )
