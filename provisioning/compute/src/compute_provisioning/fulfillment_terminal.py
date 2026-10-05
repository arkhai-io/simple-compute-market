"""Domain effects owed when a fulfillment record becomes terminal.

A record is terminal once it is ``failed``, ``torn_down``, or ``abandoned``:
nothing its provider created remains reachable through it. A domain may hold
something for the record's lifetime that must be given back then, such as a
relay port its VM was reached through. It contributes a hook, and every path
that makes a record terminal runs the hooks in the same transaction, so the
effect and the state that justifies it commit together: a crash between them
would leave something nothing claims.

The composition root creates one ``FulfillmentTerminalHooks`` registry and
hands it to everything that makes a record terminal; composing the adapter
bundles fills it and freezes it, before any of them runs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from market_fulfillment.db import SettlementRecord, SettlementRecordState

#: The states after which nothing a fulfillment created remains reachable.
#: ``teardown_failed`` is not among them: recovery retries it, and what it
#: created may still be live.
FULFILLMENT_TERMINAL_STATES = frozenset(
    {
        SettlementRecordState.failed.value,
        SettlementRecordState.torn_down.value,
        SettlementRecordState.abandoned.value,
    }
)

#: A domain's terminal effect: called with the session of the transaction
#: making the record terminal, the record's capacity reservation id, and the
#: terminal state. It writes in that session and never commits; raising aborts
#: the transaction, leaving the record as it was.
FulfillmentTerminalHook = Callable[[Any, str, str], None]


def fulfillment_is_terminal(db: Any, capacity_reservation_id: str) -> bool:
    """Whether the fulfillment for a reservation has finished.

    A reservation with no fulfillment record counts as finished: nothing was,
    or remains, delivered under it.
    """
    record = db.get(SettlementRecord, capacity_reservation_id)
    return record is None or record.state in FULFILLMENT_TERMINAL_STATES


class FulfillmentTerminalHooks:
    """Every contributed terminal effect, run in registration order.

    Filled by composition and frozen before the service accepts traffic.
    Nothing runs until it is frozen, so a record can never become terminal
    against a partially composed set of effects.
    """

    def __init__(self) -> None:
        self._hooks: list[FulfillmentTerminalHook] = []
        self._frozen = False

    def register(self, hook: FulfillmentTerminalHook) -> None:
        if self._frozen:
            raise RuntimeError("fulfillment terminal hooks are frozen")
        if not callable(hook):
            raise ValueError(f"fulfillment terminal hook {hook!r} is not callable")
        self._hooks.append(hook)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def run(self, db: Any, capacity_reservation_id: str, state: str) -> None:
        """Run every hook if ``state`` is terminal; otherwise nothing."""
        if state not in FULFILLMENT_TERMINAL_STATES:
            return
        if not self._frozen:
            raise RuntimeError("fulfillment terminal hooks have not been composed")
        for hook in self._hooks:
            hook(db, capacity_reservation_id, state)


__all__ = [
    "FULFILLMENT_TERMINAL_STATES",
    "FulfillmentTerminalHook",
    "FulfillmentTerminalHooks",
    "fulfillment_is_terminal",
]
