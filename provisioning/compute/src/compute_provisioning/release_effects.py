"""What a deployment returns exactly when a reservation's capacity is.

A domain may hold something for a reservation's lifetime, such as the relay port
its VM is reached through. It is returned when, and only when, the site releases
the reservation's capacity: a release the release guard permits, a release an
operator forces, or a hold that lapses. A fulfillment's state alone never
decides it. A ``failed`` fulfillment, in particular, may have left something
running, so its capacity stays held until an operator verifies the host and
forces the release, and what the domain holds is returned with it.

The composition root creates one ``ReleaseEffects`` registry and hands it to the
site ledger as its ``release_effect``; composing the adapter bundles fills and
freezes it. The ledger runs it in the transaction that releases the capacity,
so the two commit together, and a failing effect aborts the release.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from market_site.db import CapacityReservation, ReservationState

#: A domain's release effect: called with the session of the transaction
#: releasing a reservation's capacity, the reservation's id, and the state it
#: was released to. It writes in that session and never commits; raising
#: aborts the release.
ReleaseEffect = Callable[[Any, str, str], None]

_RELEASED_STATES = frozenset(
    {ReservationState.released.value, ReservationState.force_released.value}
)


def reservation_is_released(db: Any, capacity_reservation_id: str) -> bool:
    """Whether a reservation's capacity has been released, or never existed."""
    reservation = db.get(CapacityReservation, capacity_reservation_id)
    return reservation is None or reservation.state in _RELEASED_STATES


class ReleaseEffects:
    """Every contributed release effect, run in registration order.

    Filled by composition and frozen before the service accepts traffic.
    Nothing runs until it is frozen, so capacity is never released against a
    partially composed set of effects.
    """

    def __init__(self) -> None:
        self._effects: list[ReleaseEffect] = []
        self._frozen = False

    def register(self, effect: ReleaseEffect) -> None:
        if self._frozen:
            raise RuntimeError("release effects are frozen")
        if not callable(effect):
            raise ValueError(f"release effect {effect!r} is not callable")
        self._effects.append(effect)

    def freeze(self) -> None:
        self._frozen = True

    @property
    def frozen(self) -> bool:
        return self._frozen

    def __call__(self, db: Any, capacity_reservation_id: str, state: str) -> None:
        """Run every effect; the ledger calls this as its release effect."""
        if not self._frozen:
            raise RuntimeError("release effects have not been composed")
        for effect in self._effects:
            effect(db, capacity_reservation_id, state)


__all__ = ["ReleaseEffect", "ReleaseEffects", "reservation_is_released"]
