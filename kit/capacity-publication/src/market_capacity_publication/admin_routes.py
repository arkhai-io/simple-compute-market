"""Framework-free capacity admin routes every storefront binds.

Admin reserve takes a hold through a listing's capacity binding, as a
negotiated acceptance would, without negotiating; the capacity-released callback
is how a site tells the storefront that a reservation's capacity is free again.
What each storefront does around those — which listings close or reopen, what
its fulfillment lifecycle records — is its own, supplied as hooks. The kit owns
the request contract, the refusals, and the response shape.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .capacity import CapacityBindingError


class CapacityAdminRouteError(RuntimeError):
    """HTTP-shaped failure raised without depending on a web framework."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


#: ``(listing_id, claim, deal_ref)`` → the reservation, or ``None`` when no
#: capacity matched the claim. Raises ``CapacityBindingError`` when the listing's
#: site is not configured and ``LookupError`` when the listing has no binding.
ReserveHook = Callable[
    [str, Mapping[str, Any], Mapping[str, Any]], Awaitable[Mapping[str, Any] | None]
]
#: ``(event)`` → what the storefront recorded. Raises ``LookupError`` when the
#: reservation is unknown to the storefront.
ReleasedHook = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]


class CapacityAdminRouteService:
    """Reserve capacity administratively and record a site's release callback."""

    def __init__(self, *, reserve: ReserveHook, released: ReleasedHook) -> None:
        self._reserve = reserve
        self._released = released

    async def reserve(self, body: Mapping[str, Any]) -> dict[str, Any]:
        listing_id = str(body.get("listing_id") or "")
        if not listing_id:
            raise CapacityAdminRouteError(400, "a listing with a capacity binding is required")
        deal_ref = {"listing_id": listing_id, "reserved_by": "admin"}
        if body.get("escrow_uid"):
            deal_ref["escrow_uid"] = body["escrow_uid"]
        try:
            reserved = await self._reserve(
                listing_id, dict(body.get("required_attributes") or {}), deal_ref
            )
        except LookupError as exc:
            raise CapacityAdminRouteError(404, str(exc)) from exc
        except CapacityBindingError as exc:
            raise CapacityAdminRouteError(500, str(exc)) from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise CapacityAdminRouteError(
                502, f"could not reach the site for listing {listing_id!r}: {exc}"
            ) from exc
        if not reserved:
            raise CapacityAdminRouteError(409, "no available capacity matched the claim")
        return dict(reserved)

    async def capacity_released(self, event: Mapping[str, Any]) -> dict[str, Any]:
        if not event.get("capacity_reservation_id"):
            raise CapacityAdminRouteError(400, "capacity_reservation_id is required")
        try:
            return dict(await self._released(event))
        except LookupError as exc:
            raise CapacityAdminRouteError(404, str(exc)) from exc


__all__ = [
    "CapacityAdminRouteError",
    "CapacityAdminRouteService",
    "ReleasedHook",
    "ReserveHook",
]
