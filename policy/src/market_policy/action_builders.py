"""Action builder helpers for negotiation policies.

Provides:
  - ``make_negotiation_id``: deterministic negotiation identifier derived from a
    sorted pair of order IDs so both agents independently produce the same ID.
  - ``NegotiationActionBuilder``: thin builder that wraps ``DomainAction``
    construction to reduce boilerplate in policy callables.
"""

from __future__ import annotations

import hashlib
from typing import Any

from service.schemas import ActionType, DomainAction


def make_negotiation_id(order_id_a: str, order_id_b: str) -> str:
    """Return a deterministic negotiation ID for a pair of orders.

    Both agents independently call this with their own and the counterparty's
    order IDs. By sorting before hashing, both sides produce the same ID
    regardless of argument order. The short hex prefix keeps log output readable.

    Args:
        order_id_a: One order ID (either side).
        order_id_b: The other order ID.

    Returns:
        A string of the form ``"neg_<16-hex-chars>"``.
    """
    canonical = sorted([order_id_a, order_id_b])
    digest = hashlib.sha256("|".join(canonical).encode()).hexdigest()
    return f"neg_{digest[:16]}"


class NegotiationActionBuilder:
    """Builder for ``DomainAction`` objects in negotiation policy callables.

    Accepts a context ``data`` dict (negotiation_id, order IDs, prices, etc.)
    that is merged into the ``parameters`` of every action produced. This
    keeps policy functions free of repetitive ``DomainAction(...)`` boilerplate.

    Usage::

        actions = NegotiationActionBuilder({
            "negotiation_id": neg_id,
            "our_order_id": our_order_id,
            "their_order_id": their_order_id,
            "proposed_price": their_price,
        })
        return actions.counter(new_price)
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def _build(self, action_type: ActionType, extra: dict[str, Any]) -> DomainAction:
        return DomainAction(
            action_type=action_type,
            parameters={**self._data, **extra},
        )

    def accept(self, reason: str = "") -> DomainAction:
        """Accept the current offer."""
        return self._build(ActionType.ACCEPT_OFFER, {"reason": reason})

    def reject(self, reason: str = "") -> DomainAction:
        """Reject the offer outright (no counter)."""
        return self._build(ActionType.REJECT_OFFER, {"reason": reason})

    def counter(self, proposed_price: Any, reason: str = "") -> DomainAction:
        """Counter-offer with *proposed_price*."""
        return self._build(
            ActionType.COUNTER_OFFER,
            {"proposed_price": proposed_price, "reason": reason},
        )

    def exit(self, reason: str = "") -> DomainAction:
        """Exit the negotiation cleanly."""
        return self._build(ActionType.EXIT_NEGOTIATION, {"reason": reason})
