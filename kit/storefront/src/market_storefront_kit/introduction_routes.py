"""The answer a storefront gives a deal settled outside settlement.

A seller stage whose mechanism completes outside settlement and fulfillment, as
an introduction does, has no settle, delivery, or refund operation. Every
storefront answers such a deal's settle and fulfillment requests here, from the
declaration of the stage the deal's accepted Agreement selected, never from a
mechanism identifier, the listing's backing, or whether the stage fulfils
through capacity: a mechanism that settles without delivering through capacity
still has a settle operation. The domain resolves the stage and supplies the
reason text, which names its mechanism; this module owns the decision and the
status codes.
"""

from __future__ import annotations

from .lifecycle_routes import LifecycleRouteError


def refuse_introduction_settle(
    *, completes_outside_settlement: bool, reason: str
) -> None:
    """Refuse a settle request for a deal its stage completes outside settlement.

    Raises ``LifecycleRouteError`` with 409: the deal exists and is accepted,
    and settling it is the wrong operation for it.
    """

    if completes_outside_settlement:
        raise LifecycleRouteError(409, reason)


def refuse_introduction_fulfillment(
    *, completes_outside_settlement: bool, reason: str
) -> None:
    """Refuse a fulfillment read or teardown for a deal with no fulfillment.

    Raises ``LifecycleRouteError`` with 404, since no fulfillment exists. The
    caller checks ownership first, so only the deal's buyer learns why.
    """

    if completes_outside_settlement:
        raise LifecycleRouteError(404, reason)


__all__ = ["refuse_introduction_fulfillment", "refuse_introduction_settle"]
